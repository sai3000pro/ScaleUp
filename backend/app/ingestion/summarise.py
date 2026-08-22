"""Write the caption under a node, from the book's own words.

`outline_concepts` used to set `summary = own_text[:280]`. That is not a summary,
it is an excerpt of whatever happened to be printed first inside the node's page
range -- and on a real textbook the first 280 characters of a section are
routinely a *different concept*. Measured on CO 250:

    The KKT Theorem   "Definition Let f : Rn -> R be a function. The epigraph
                       of f is given by ..."

The node the whole chapter builds towards was captioned with the definition of
an epigraph, because section 5.2 opens with the tail of 5.1. For a product whose
claim is "graphs that teach", every node's caption taught the wrong thing.

## What replaces it

Three ideas, in order of strength, all read out of the source rather than
invented:

1. **The sentence that names the node's own title.** A textbook states what a
   thing is in the sentence that first uses its name. "We define the matrix
   product AB = C to be ..." is the caption for `Matrix product`; the section's
   opening line is not.
2. **The `Definition:` / `Theorem:` lead-in the book itself marks.** Detection is
   NOT reimplemented here -- `app.ingestion.segment.find_lead_in` already owns
   the marker vocabulary and what counts as a lead-in, and it is called on the
   opening words of each sentence. Teaching the detector a new convention
   (`LeadInMarkers`) therefore teaches this module too.
3. **The first readable prose sentence**, which is what the old code did by
   accident and is still the right last resort.

## Why a token filter is doing most of the work

A PDF text layer of a LaTeX book is mostly not prose. 82% of extracted lines on
CO 250 are one-to-four-token fragments -- `C = AB = A h b1 b2 · · · bp i` is what
a matrix display becomes once the glyphs are flattened into a line. Any rule that
picks "the first sentence" without a notion of readability picks one of those.

So a token is *wordy* only if it is a plain alphabetic word of at least two
letters, and a run of four or more non-wordy tokens collapses to an ellipsis. The
same test decides whether a sentence is prose at all. This is deliberately blind
to meaning: it cannot tell a good caption from a bad one, only readable text from
flattened mathematics, which is the failure this module exists to fix.

Pure. No I/O, no database, no LLM -- `summarise_nodes` is the only function here
that touches the seam, and it is off unless a real provider is configured.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.sync_bridge import run_sync
from app.ingestion.segment import (
    DANGLING_WORDS,
    DEFINING_KINDS,
    TEXTBOOK_MARKERS,
    LeadInMarkers,
    find_lead_in,
    normalise_title,
)
from app.llm.base import LLMClient, LLMRole, RefusalError, SchemaValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "SUMMARY_CHARS",
    "NodeBrief",
    "split_statements",
    "is_prose",
    "strip_math",
    "lead_in_of",
    "section_summary",
    "render_briefs",
    "summarise_nodes",
]

# ── thresholds ────────────────────────────────────────────────────────────

# Unchanged from the excerpt it replaces: this is what the inspector renders and
# what `prereqs._render_skill_list` truncates to 110 characters.
SUMMARY_CHARS = 280
# Below this the chosen sentence is a fragment, so following prose is appended
# until the caption is worth reading.
TOPUP_FLOOR = 120
# A run of this many non-wordy tokens is a flattened formula, not punctuation.
MATH_RUN = 4
# Fewer real words than this and the sentence is a caption, an axis label, or a
# line of algebra that happened to contain a verb.
MIN_PROSE_WORDS = 4
MIN_PROSE_RATIO = 0.4
# How far into a sentence a lead-in may run. `Definition: Matrix Multiplication`
# is four words; anything longer is the pattern eating the statement itself.
LEAD_IN_MAX_WORDS = 4
# A one-character "title" cannot be matched against prose without matching
# everything.
MIN_TITLE_CHARS = 3
# How far back a caption may reach to find the head of its own clause.
MAX_BACKFILL = 2
ELLIPSIS = "…"

# Stripped before a token is tested, so `(non-singular).` reads as a word.
_EDGE_PUNCTUATION = "()[]{}.,;:!?\"'“”‘’`-–—"
# A plain word. Deliberately ASCII-only: the moment a token carries a maths glyph
# -- ⊤, ∈, ≥, ⃗ -- it is part of a formula, whatever letters sit next to it.
_WORD = re.compile(r"^[A-Za-z][A-Za-z'’-]*$")
# Bullets run several sentences together in a flattened text layer. `·` is
# deliberately NOT one of them: in a maths book the middle dot is the ellipsis
# inside `x1, x2, · · · , xn`, and treating it as a list marker cuts every
# indexed family in half -- which is how "KKT Theorem Let I denote ..." became
# two statements, neither of which reads.
_BULLET = re.compile(r"\s+[•▪▶‣]\s*")
_PERIOD = re.compile(r"\.(?=\s)")
# The token immediately before a full stop, when it is long enough to be a word
# rather than a variable. `s.t.` and `i.e.` fail this, which is the point.
_TAIL_TOKEN = re.compile(r"[A-Za-z0-9)\]}]{2,}\.$")
# ... unless what follows unmistakably opens a new sentence.
_NEXT_SENTENCE = re.compile(r"^\s+[A-Z][a-z]")
# A dash after the node's title means the book is naming a *variant* of it --
# "KKT Theorem - Subgradient" is not the KKT Theorem.
_VARIANT_MARK = frozenset({"-", "–", "—", ":", "--"})

# Ranks, strongest first. A tie is broken by position, so the earliest sentence
# at the winning rank is the one the book leads with.
_RANK_TITLE_HEADS = 4  # the sentence opens with the node's own title
_RANK_DEFINES_TITLE = 3  # opens with `Definition`/`Theorem` AND names the title
_RANK_NAMES_TITLE = 2  # names the title anywhere
_RANK_DEFINITION = 1  # opens with `Definition`/`Theorem`
_RANK_PROSE = 0


# ── readability ───────────────────────────────────────────────────────────


def _is_wordy(token: str) -> bool:
    core = token.strip(_EDGE_PUNCTUATION)
    return len(core) >= 2 and _WORD.match(core) is not None


def _wordy_count(statement: str) -> tuple[int, int]:
    tokens = statement.split()
    return sum(1 for token in tokens if _is_wordy(token)), len(tokens)


def is_prose(statement: str) -> bool:
    """Enough real words, densely enough, to be worth showing a learner.

    Measured on the COLLAPSED form, and on the collapse alone -- never on the
    tidied one. A definition with a display formula welded onto its end -- "We
    define the matrix product AB = C to be ... C = AB = A h b1 b2 · · · bp i = h
    A⃗b1 ..." -- is 35% wordy as it stands and 76% wordy once the formula becomes
    an ellipsis, so judging it before the collapse rejects the one sentence in
    the section that says what the node is. Judging it *after* `_tidy` is the
    opposite error: tidy drops the trailing conjunction, which took "Definition
    Suppose a constraint α⊤x ≤β that" under the four-word floor and made the
    head of a bulleted definition unquotable.
    """
    wordy, total = _wordy_count(" ".join(_collapse(statement)))
    return wordy >= MIN_PROSE_WORDS and total > 0 and wordy / total >= MIN_PROSE_RATIO


def split_statements(text: str) -> list[str]:
    """Sentences, as well as a flattened PDF text layer supports the idea.

    Splitting on `(?<=[.!?])\\s+` -- what `chunking.py` does, correctly, for its
    own purpose -- shatters mathematics: `min c⊤x s.t. Ax ≥ b` becomes three
    "sentences", two of which are the letters `s` and `t`. So a full stop only
    ends a sentence when the token in front of it is at least two characters
    long, or when what follows unambiguously starts a new one.
    """
    flat = " ".join(text.split())
    pieces: list[str] = []
    start = 0

    for match in _PERIOD.finditer(flat):
        head = flat[start : match.end()]
        ends_a_word = _TAIL_TOKEN.search(head) is not None
        opens_a_sentence = _NEXT_SENTENCE.match(flat[match.end() :]) is not None
        if ends_a_word or opens_a_sentence:
            pieces.append(head.strip())
            start = match.end()

    tail = flat[start:].strip()
    if tail:
        pieces.append(tail)

    statements: list[str] = []
    for piece in pieces:
        for part in _BULLET.split(piece):
            cleaned = part.strip().lstrip("•▪▶‣ ")
            if cleaned:
                statements.append(cleaned)
    return statements


def _collapse(statement: str) -> list[str]:
    """Tokens with every long run of non-words replaced by one ellipsis.

    `AB = C` is three tokens and survives, because a caption that cannot say what
    it is about is no better than a formula. `C = AB = A h b1 b2 · · · bp i = h
    A⃗b1 A⃗b2 · · · A⃗bp i` is nineteen and becomes an ellipsis.
    """
    kept: list[str] = []
    pending: list[str] = []

    for token in statement.split():
        if _is_wordy(token):
            if len(pending) >= MATH_RUN:
                kept.append(ELLIPSIS)
            else:
                kept.extend(pending)
            pending = []
            kept.append(token)
        else:
            pending.append(token)

    if len(pending) >= MATH_RUN:
        kept.append(ELLIPSIS)
    else:
        kept.extend(pending)

    return kept


def strip_math(statement: str) -> str:
    return _tidy(_collapse(statement))


def _tidy(tokens: Sequence[str]) -> str:
    """Drop leading ellipses and trailing half-clauses, then close the sentence."""
    words = list(tokens)

    # A word marooned between two formulae -- "|{z} fixed + t |{z}" collapses to
    # "… fixed …" -- is a fragment of a display, not the start of a caption.
    stripping = True
    while stripping:
        stripping = False
        while words and words[0] == ELLIPSIS:
            words.pop(0)
        if len(words) > 2 and words[1] == ELLIPSIS:
            words.pop(0)
            stripping = True

    while words and (words[-1] == ELLIPSIS and len(words) > 1 and words[-2] == ELLIPSIS):
        words.pop()
    # "... consider the NLP: min … where" -- a conjunction left hanging by the
    # collapse reads as a truncation bug rather than as an elision.
    while words and words[-1].strip(_EDGE_PUNCTUATION).lower() in DANGLING_WORDS:
        words.pop()

    text = " ".join(words).strip()
    if not text:
        return ""
    if text.endswith(ELLIPSIS) or text[-1] in ".!?":
        return text
    return text.rstrip(" ,;:-–—") + ELLIPSIS


# ── lead-ins, read through `segment.find_lead_in` ─────────────────────────


def lead_in_of(statement: str, markers: LeadInMarkers = TEXTBOOK_MARKERS) -> tuple[str, str] | None:
    """`(phrase, kind)` if this sentence opens with a lead-in, else None.

    The SHORTEST matching prefix wins. `find_lead_in` is anchored to a whole
    line, and a line is exactly what a flattened text layer no longer has -- so
    `Definition: Matrix Multiplication Let A ...` matches at four words and at
    six, and the longer match has swallowed the statement the lead-in announces.
    """
    words = statement.split()
    found: tuple[str, str] | None = None
    count = 1

    while found is None and count <= min(LEAD_IN_MAX_WORDS, len(words)):
        phrase = " ".join(words[:count])
        detected = find_lead_in(phrase, markers)
        if detected is not None:
            found = (phrase, detected[0])
        count += 1

    return found


def _normalised_words(text: str) -> list[str]:
    """`normalise_title` applied to running prose rather than to a title.

    Punctuation is stripped BEFORE it, not after: `normalise_title` folds a
    trailing plural `s`, and `points,` does not end in `s`, so a comma is enough
    to stop "Extreme Points" matching "extreme points, which are".
    """
    stripped = " ".join(word.strip(_EDGE_PUNCTUATION) for word in text.split())
    return normalise_title(stripped).split()


def _heads_with(statement_words: Sequence[str], title_words: Sequence[str], statement: str) -> bool:
    if list(statement_words[: len(title_words)]) != list(title_words):
        return False
    after = statement.split()[len(title_words) : len(title_words) + 1]
    return not (after and after[0] in _VARIANT_MARK)


def _contains(statement_words: Sequence[str], title_words: Sequence[str]) -> bool:
    span = len(title_words)
    return any(
        list(statement_words[at : at + span]) == list(title_words)
        for at in range(len(statement_words) - span + 1)
    )


def _rank(statement: str, title_words: Sequence[str], markers: LeadInMarkers) -> int:
    words = _normalised_words(statement)
    names = bool(title_words) and _contains(words, title_words)
    lead_in = lead_in_of(statement, markers)
    defines = lead_in is not None and lead_in[1] in DEFINING_KINDS

    if names and _heads_with(words, title_words, statement):
        return _RANK_TITLE_HEADS
    if names and defines:
        return _RANK_DEFINES_TITLE
    if names:
        return _RANK_NAMES_TITLE
    if defines:
        return _RANK_DEFINITION
    return _RANK_PROSE


def _render(statement: str, markers: LeadInMarkers) -> str:
    """One sentence, cleaned, with its lead-in label punctuated as a label.

    `Definition Let B be a subset` is how the text layer prints a display label
    over a statement; `Definition. Let B be a subset` is what it means.
    """
    lead_in = lead_in_of(statement, markers)
    if lead_in is None or lead_in[0][-1] in ".:;":
        return strip_math(statement)

    phrase = lead_in[0]
    rest = statement[len(phrase) :].lstrip()
    # Only when a sentence genuinely follows. "The Certificate of Optimality is
    # then the scalars vector" is one sentence whose subject happens to be a
    # named result, and punctuating it gives ". is then", which reads as a bug.
    if not rest[:1].isupper():
        return strip_math(statement)
    return strip_math(f"{phrase}. {rest}")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-–—") + ELLIPSIS


# ── the deterministic summariser ──────────────────────────────────────────

# A leading article is not part of the name a book uses in its prose: the section
# is called "The KKT Theorem" and the theorem is stated as "KKT Theorem".
_ARTICLES = frozenset({"the", "a", "an"})


def section_summary(
    title: str,
    text: str,
    *,
    limit: int = SUMMARY_CHARS,
    markers: LeadInMarkers = TEXTBOOK_MARKERS,
) -> str:
    """The best caption the book itself supports, or `""` if it supports none.

    Returning `""` is a real answer -- a heading that owns no prose has nothing
    to summarise, and the caller's page-range placeholder is more honest than a
    sentence borrowed from somewhere else.
    """
    statements = split_statements(text)
    if not statements:
        return ""

    title_words = [word for word in _normalised_words(title) if word not in _ARTICLES]
    if len(" ".join(title_words)) < MIN_TITLE_CHARS:
        title_words = []

    best_rank, chosen = -1, -1
    for index, statement in enumerate(statements):
        if not is_prose(statement):
            pass
        else:
            rank = _rank(statement, title_words, markers)
            if rank > best_rank:
                best_rank, chosen = rank, index

    if chosen < 0:
        return ""

    start = _clause_start(statements, chosen)
    body = " ".join(statements[start : chosen + 1])
    summary = _render(body, markers)

    # Top up a one-line caption with the prose that follows it -- but never past
    # the next lead-in. A caption that runs on into `Remark ...` has stopped
    # describing this concept and started describing the next one.
    for statement in statements[chosen + 1 :]:
        if len(summary) >= TOPUP_FLOOR or lead_in_of(statement, markers) is not None:
            break
        if is_prose(statement):
            summary = f"{summary} {strip_math(statement)}".strip()

    return _truncate(summary, limit)


def _clause_start(statements: Sequence[str], chosen: int) -> int:
    """Walk back to the head of the clause the chosen sentence belongs to.

    A bullet list in a flattened text layer arrives as `Definition Suppose a
    constraint that | is satisfied for all feasible solutions | is not satisfied
    for x We then call this a cutting plane`. The sentence naming the concept is
    the third of those, and shown alone it opens mid-clause with a bare verb.
    """
    start = chosen
    steps = 0
    while start > 0 and steps < MAX_BACKFILL and statements[start][:1].islower():
        previous = statements[start - 1]
        if not is_prose(previous):
            break
        start -= 1
        steps += 1
    return start


# ── the LLM upgrade, behind the same seam ─────────────────────────────────

# One call covers this many nodes. Small enough that a schema failure costs a
# handful of captions rather than the book's, large enough that a 200-node
# textbook is a dozen calls and not two hundred.
NODE_BATCH = 12
# How much of a node's own text the model is shown. A caption needs the opening
# statement, not the worked example underneath it.
NODE_EXCERPT_CHARS = 1200
MIN_MODEL_SUMMARY = 20
MAX_MODEL_SUMMARY = 400


@dataclass(frozen=True, slots=True)
class NodeBrief:
    """What the summarising role is shown about one node."""

    slug: str
    title: str
    text: str


def render_briefs(briefs: Sequence[NodeBrief], excerpt_chars: int = NODE_EXCERPT_CHARS) -> str:
    """The node listing the prompt shows the model.

    Machine-parseable, like `segment.render_fragments`, so the deterministic
    provider reads the same rendering a real one does and the fake exercises the
    real code path rather than a shortcut around it.
    """
    return "\n\n".join(
        f"### `{brief.slug}` — {brief.title}\n{' '.join(brief.text.split())[:excerpt_chars]}"
        for brief in briefs
    )


def _usable(summary: str, title: str) -> bool:
    """Reject a caption that restates the title or is too short to teach.

    Same discipline as `segment._is_usable_title`: the deterministic summary is a
    real fallback, so there is no reason to accept a worse answer from a model.
    """
    cleaned = " ".join(summary.split())
    if not (MIN_MODEL_SUMMARY <= len(cleaned) <= MAX_MODEL_SUMMARY):
        return False
    return normalise_title(cleaned) != normalise_title(title)


def summarise_nodes(
    client: LLMClient,
    book_title: str,
    briefs: Sequence[NodeBrief],
    *,
    course_id: str | None = None,
    batch_size: int = NODE_BATCH,
) -> dict[str, str]:
    """slug -> model-written caption, for the nodes the model answered usably.

    Absorbed per batch, exactly as window extraction and fragment naming are: a
    node whose caption fails to come back keeps the deterministic one, which is
    the whole reason the deterministic path is built first.
    """
    written: dict[str, str] = {}
    by_slug = {brief.slug: brief for brief in briefs}

    for start in range(0, len(briefs), batch_size):
        group = list(briefs[start : start + batch_size])
        try:
            result = run_sync(
                client.structured(
                    LLMRole.NODE_SUMMARY,
                    {
                        "book_title": book_title,
                        "node_count": len(group),
                        "nodes": render_briefs(group),
                    },
                    course_id=course_id,
                )
            )
        except (SchemaValidationError, RefusalError) as exc:
            logger.warning("node summarising failed for %s nodes from %s: %s", len(group), start, exc)
        else:
            _absorb(result.data.get("summaries", []), by_slug, written)

    return written


def _absorb(
    returned: Sequence[Mapping[str, object]],
    by_slug: Mapping[str, NodeBrief],
    written: dict[str, str],
) -> None:
    """Keep only captions for nodes that were actually shown.

    The prompt says the slug list is closed; this is what makes it true.
    """
    for item in returned:
        slug = str(item.get("slug", ""))
        summary = " ".join(str(item.get("summary", "")).split())
        brief = by_slug.get(slug)
        if brief is None:
            logger.debug("discarding a summary for an unknown slug: %s", slug)
        elif not _usable(summary, brief.title):
            logger.debug("discarding an unusable summary for %s", slug)
        else:
            written[slug] = summary[:SUMMARY_CHARS]
