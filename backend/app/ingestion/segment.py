"""Split a table-of-contents section into the concepts it actually introduces.

`toc.py` maps one outline entry to exactly one node, and there is nothing below
it. Measured against a hand-authored reference tree for CO 250, that is 44 nodes
for 79 real concepts -- and the under-segmentation is worst exactly where the
material is hardest. One node called "The KKT Theorem" holds Subgradient,
Supporting half-spaces, Linear relaxation of an NLP, the subgradient form of
KKT, Gradient as a subgradient, Slater point and the KKT Theorem itself. A
learner cannot be told which of those seven they have not learned, and 45 of the
reference's 122 prerequisite edges are unexpressible because both endpoints sit
inside one node.

**The book already marks its own concept boundaries. Do not ask a model to
invent them.** Every concept in this textbook is introduced by a literal lead-in
on its own line -- `Definition`, `Definition: Matrix Multiplication`, `Remark 1`,
`Theorem: Farka's Lemma`, `KKT Theorem - Subgradient`, `Weak Duality Theorem`.
Those lines are found here, structurally, in pure Python. A model is used only
to *name and summarise* the fragments that result, from text it can already see.

That division is the whole argument for TOC-first extraction, applied one level
down. When a model was allowed to choose boundaries on this same book it
produced nodes called "Consider", "Slacky" and "Endpoint". It is reliable at
describing a passage it is handed and unreliable at deciding where a passage
starts, so it is only asked to do the former.

The one thing the model may change about the segmentation is to *remove* a
boundary: `standalone: false` folds a fragment into the one above it. Merging is
the safe direction -- it can lose a distinction the book drew, but it can never
manufacture one the book did not.

The marker vocabulary is an INPUT, not a hardcoded rule. `Definition:` /
`Theorem:` on its own line is a LaTeX-textbook convention; a converted ebook or
a deck of lecture slides has no such convention, and on those books the detector
finds nothing and every section stays exactly one node -- current behaviour,
which is correct. Silence on an unmarked book is the designed outcome; guessing
on one is not. `LeadInMarkers` is the seam for teaching it a new convention.

Boundary detection is pure: no I/O, no database, no LLM, testable in
milliseconds. Only `_name_fragments` and `segment_sections` touch the LLM seam.
"""

from __future__ import annotations

import logging
import re
import uuid
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Container, Protocol, Sequence

from app.core.sync_bridge import run_sync
from app.ingestion.toc import slugify
from app.llm.base import LLMClient, LLMRole, RefusalError, SchemaValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "ChunkRef",
    "LeadInMarkers",
    "TEXTBOOK_MARKERS",
    "SectionInput",
    "RawFragment",
    "Fragment",
    "SegmentOutcome",
    "find_lead_in",
    "section_line_spans",
    "split_section",
    "FirstMention",
    "title_candidates",
    "fallback_title",
    "normalise_title",
    "structural_title",
    "segment_sections",
]

# ── thresholds ────────────────────────────────────────────────────────────
#
# Not every section should split, and the cost of splitting one that should not
# is a node with no teachable content in it. `matrix-inequality` is 328
# characters holding exactly one definition; it must survive this file unchanged.

# Below this a section has no room for two concepts, whatever its lead-ins say.
MIN_SECTION_CHARS = 600
# A fragment shorter than this is a stub -- a one-line corollary, a stray
# lead-in over a formula -- and is folded into the fragment above it rather than
# becoming a node nobody can be assessed on.
MIN_FRAGMENT_CHARS = 120
# One concept-bearing fragment is not a segmentation; it is the section.
MIN_FRAGMENTS = 2
# The ceiling scales with the section, because sections do. A CO 250 section is
# two pages; a CS 251 section is thirty, and capping both at one constant either
# throws away the long book's segmentation or lets a misfiring detector shred
# the short one. Expressed per page with a floor, so the invariant is "a
# fragment averages at least a few paragraphs" rather than "a section has at
# most N concepts".
MAX_FRAGMENTS_PER_PAGE = 8
MAX_FRAGMENTS_FLOOR = 12
# How much of a fragment the naming call sees. Enough to contain the definiendum
# and the statement; the rest is worked arithmetic.
FRAGMENT_PROMPT_CHARS = 900
SUMMARY_CHARS = 280
# How far into a fragment the no-model namer looks for the thing being defined.
DEFINIENDUM_SEARCH_CHARS = 240
# `slugify` caps at 64 and the edge schemas enforce it. Leaving room for a
# "-2" de-duplicating suffix is what keeps a long section title inside it.
MAX_SLUG_CHARS = 58
# A node in a skill tree is a name, not a sentence. Anything longer is a pattern
# that ran past the end of the phrase it was matching.
MAX_TITLE_WORDS = 4
# How far above a fragment a term may already have been used and still count as
# introduced by it -- one page, for a definition motivated in the paragraph above.
FIRST_MENTION_SLACK_PAGES = 1

# ── lead-in vocabulary ────────────────────────────────────────────────────

# Ignored when testing a line for Title Case, so "Certificate of Optimality" and
# "Cone of Tight Constraints" still read as titles.
SMALL_WORDS = frozenset("a an and as at by for from in of on or the to with is are its".split())

# Kinds whose text belongs to the concept above them.
_ATTACHING = "illustration"
_PREAMBLE = "preamble"


@dataclass(frozen=True, slots=True)
class LeadInMarkers:
    """The boundary convention a book uses, as data.

    Stated rather than buried, because it is a property of the SOURCE and not of
    this algorithm. `Definition:` on its own line is how LaTeX textbooks are
    written; a converted ebook, a lecture deck, or a paper marks its concepts
    some other way or not at all. Swapping this object teaches the detector a
    new convention without touching a line of the splitting logic; supplying an
    empty one turns segmentation off, which is the honest behaviour for a source
    that marks nothing.
    """

    # The passage under one of these defines or states something examinable.
    concept_keywords: frozenset[str]
    # The passage under one of these ILLUSTRATES the concept above it.
    attach_keywords: frozenset[str]
    # Words that make a bare Title Case line a *named result* rather than prose:
    # "Weak Duality", "Perfect Matching Theorem", "KKT Theorem - Subgradient".
    # Empty disables named-result detection entirely.
    result_nouns: frozenset[str] = frozenset()

    def kind_for(self, word: str) -> str | None:
        lowered = word.lower()
        if lowered in self.attach_keywords:
            return _ATTACHING
        if lowered in self.concept_keywords:
            return lowered[:-1] if lowered.endswith("s") else lowered
        return None


TEXTBOOK_MARKERS = LeadInMarkers(
    concept_keywords=frozenset(
        """definition definitions theorem theorems lemma lemmas corollary corollaries
        proposition propositions remark remarks observation observations fact facts
        claim claims note notes property properties notation axiom axioms algorithm
        algorithms procedure procedures""".split()
    ),
    attach_keywords=frozenset(
        """example examples exercise exercises proof proofs solution solutions""".split()
    ),
    result_nouns=frozenset(
        """theorem theorems lemma lemmas corollary proposition duality slackness rule rules
        algorithm criterion principle procedure optimality unboundedness infeasibility
        inequality identity axiom conjecture""".split()
    ),
)

# `Definition`, `Remark 1`, `Definition: Matrix Multiplication`,
# `KKT Theorem - Subgradient` when it starts with a keyword, and nothing else on
# the line. Anchored at both ends on purpose: "Definition of a basis is the" is
# prose, and treating it as a boundary is how the previous concept loses its
# statement to the next node.
_KEYWORD_LEAD_IN = re.compile(
    r"^(?P<word>[A-Za-z]+)\s*(?P<number>\d+(?:\.\d+)*)?\s*(?:[:–—-]\s*(?P<name>\S.{0,58}?))?[.:]?$"
)

_WORDS = re.compile(r"[A-Za-z][A-Za-z'’]*")
_MAX_NAMED_RESULT_CHARS = 60
_MAX_NAMED_RESULT_WORDS = 7


class ChunkRef(Protocol):
    """The three fields segmentation needs from a chunk.

    A Protocol rather than a dataclass so `app.models.Chunk` satisfies it as-is
    and this module never has to import the ORM -- which would invert the
    layering it sits in.
    """

    id: uuid.UUID
    page_start: int
    page_end: int


@dataclass(frozen=True, slots=True)
class SectionInput:
    """One TOC section, as `_toc_graph` already has it."""

    slug: str
    title: str
    level: int
    page_start: int  # 0-based, inclusive -- TocNode.page_start
    page_end: int  # 0-based, EXCLUSIVE -- TocNode.page_end
    difficulty: int
    chunks: tuple[ChunkRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RawFragment:
    """A fragment as the *book* delimits it, before anything is named."""

    ordinal: int
    lead_in: str  # the literal line, "" for a section preamble
    kind: str  # "definition" | "theorem" | "remark" | "named" | "preamble" | ...
    lines: tuple[str, ...]
    page_start: int  # 0-based, inclusive
    page_end: int  # 0-based, EXCLUSIVE

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()

    @property
    def body(self) -> str:
        """The fragment without its lead-in line -- what it actually says."""
        return "\n".join(self.lines[1:]).strip() if self.lead_in else self.text


@dataclass(frozen=True, slots=True)
class Fragment:
    """A named sub-section concept, ready to become a ConceptSpec."""

    parent_slug: str
    slug: str
    title: str
    summary: str
    lead_in: str
    kind: str
    text: str
    page_start: int  # 0-based, inclusive
    page_end: int  # 0-based, EXCLUSIVE
    difficulty: int
    level: int
    source_chunk_ids: tuple[uuid.UUID, ...] = ()
    key_terms: tuple[str, ...] = ()
    named_by_model: bool = False


@dataclass(slots=True)
class SegmentOutcome:
    """Fragments per section slug, plus what happened, for the job detail."""

    fragments: dict[str, list[Fragment]] = field(default_factory=dict)
    sections_seen: int = 0
    sections_split: int = 0
    sections_kept_whole: int = 0
    sections_named: int = 0
    sections_naming_failed: int = 0
    fragments_total: int = 0
    fragments_merged_by_model: int = 0
    # Dropped because their strongest name was the section's own -- they ARE the
    # section, and it is already a node.
    fragments_are_the_section: int = 0
    # Folded into an existing node because the book said "Recall that ...".
    fragments_merged_as_restatement: int = 0

    def all_fragments(self) -> list[Fragment]:
        return [fragment for section in self.fragments.values() for fragment in section]


# ── structural boundary detection ─────────────────────────────────────────


def _is_named_result(line: str, markers: LeadInMarkers) -> bool:
    """A Title Case line naming a result, with no keyword to announce it.

    Deliberately narrow. The same book puts "True", "Start", "Machine 1",
    "Consider the LP:" and "Profit from sales" on their own lines, and a rule
    that says "short capitalised line" swallows every one of them. Requiring a
    result noun AND Title Case AND no terminal punctuation is what separates
    "Weak Duality" from "We have:".
    """
    if not markers.result_nouns:
        return False
    if not (2 <= len(line) <= _MAX_NAMED_RESULT_CHARS):
        return False
    if line.endswith((".", ",", ";", ":", "?", "!")):
        return False
    # Running headers in a LaTeX book are the section title in full caps. They
    # would otherwise match on every page of the section.
    if not any(character.islower() for character in line):
        return False

    words = _WORDS.findall(line)
    if not (1 <= len(words) <= _MAX_NAMED_RESULT_WORDS):
        return False
    if not any(word.lower() in markers.result_nouns for word in words):
        return False
    return all(word[0].isupper() for word in words if word.lower() not in SMALL_WORDS)


def find_lead_in(line: str, markers: LeadInMarkers = TEXTBOOK_MARKERS) -> tuple[str, str] | None:
    """`(kind, explicit_name)` if this line opens a fragment, else None.

    `explicit_name` is the part after a colon or dash -- "Matrix Multiplication"
    from "Definition: Matrix Multiplication" -- and is "" when the book did not
    name the thing on the lead-in line itself.
    """
    stripped = line.strip()
    if not stripped:
        return None

    match = _KEYWORD_LEAD_IN.match(stripped)
    if match is not None:
        kind = markers.kind_for(match.group("word"))
        if kind is not None:
            return kind, (match.group("name") or "").strip()

    if _is_named_result(stripped, markers):
        return "named", stripped
    return None


def _is_furniture(line: str, edge_counts: Counter[str]) -> bool:
    """Running header or page number.

    Both sit at the top or bottom of every page and would otherwise open or
    pollute a fragment on each one.
    """
    if line.isdigit():
        return True
    return edge_counts.get(line, 0) >= 3 and not any(character.islower() for character in line)


def _edge_line_counts(page_texts: Sequence[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in page_texts:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for line in lines[:1] + lines[-1:]:
            counts[line] += 1
    return counts


def _heading_offset(lines: Sequence[str], title: str) -> int:
    """Index of a section's own heading line on its first page, or -1.

    Sections do not begin at a page break. Page 83 of CO 250 carries the tail of
    5.1 Convexity -- the epigraph -- and then the heading of 5.2. Page-granular
    ownership hands the whole page to 5.2 and loses the epigraph inside it.
    Cutting at the heading line instead gives each section the lines that are
    actually its own.

    Exact match first: the running header on that same page reads
    "5.2. THE KKT THEOREM", which a case-insensitive match would find *above*
    the real heading and so would claim the previous section's tail.
    """
    for index, line in enumerate(lines):
        if line.strip() == title.strip():
            return index

    lowered = title.strip().lower()
    found = -1
    for index, line in enumerate(lines):
        if line.strip().lower() == lowered:
            found = index
    return found


def section_line_spans(
    sections: Sequence[SectionInput], page_texts: Sequence[str]
) -> dict[str, list[tuple[int, str]]]:
    """slug -> `(page_index, line)` in reading order, furniture removed.

    Each section runs from its own heading line to the next section's heading
    line, so a section that starts halfway down a page does not swallow the
    previous one's last concept.
    """
    edge_counts = _edge_line_counts(page_texts)

    pages: list[list[str]] = []
    for text in page_texts:
        kept = [line.strip() for line in text.split("\n") if line.strip()]
        pages.append([line for line in kept if not _is_furniture(line, edge_counts)])

    # Shallowest first at a shared page: a chapter heading precedes the first
    # section under it on the same page, so the chapter's own span is the few
    # lines of introduction between them.
    ordered = sorted(sections, key=lambda s: (s.page_start, s.level))

    # (page_index, line_index) of each section's own HEADING line.
    starts: list[tuple[int, int]] = []
    for section in ordered:
        page = min(max(section.page_start, 0), max(len(pages) - 1, 0))
        page_lines = pages[page] if pages else []
        starts.append((page, _heading_offset(page_lines, section.title)))

    spans: dict[str, list[tuple[int, str]]] = {}
    for index, section in enumerate(ordered):
        start_page, heading_line = starts[index]
        # Skip the heading itself. It is the section's own title, and left in it
        # reads as a named-result lead-in ("The KKT Theorem", "Weak Duality")
        # that opens a fragment duplicating the parent node. `-1` means the
        # heading is not on the page at all -- a printed contents entry whose
        # wording differs from the running text -- and then there is nothing to
        # skip and the first line of the page is content.
        start_line = heading_line + 1 if heading_line >= 0 else 0
        if index + 1 < len(ordered):
            end_page, end_line = starts[index + 1]
            end_line = max(end_line, 0)
        else:
            end_page, end_line = max(section.page_end, start_page + 1), 0

        collected: list[tuple[int, str]] = []
        for page in range(start_page, min(end_page + 1, len(pages))):
            page_lines = pages[page]
            first = start_line if page == start_page else 0
            last = end_line if page == end_page else len(page_lines)
            collected.extend((page, line) for line in page_lines[first:last])
        spans[section.slug] = collected

    return spans


def _merge(into: RawFragment, tail: RawFragment) -> RawFragment:
    return replace(
        into,
        lines=into.lines + tail.lines,
        page_end=max(into.page_end, tail.page_end),
    )


def _cut(section_lines: Sequence[tuple[int, str]], markers: LeadInMarkers) -> list[RawFragment]:
    """Cut at every lead-in. Fragment 0 is the preamble, possibly empty."""
    fragments: list[RawFragment] = []
    current_kind = _PREAMBLE
    current_lead_in = ""
    current_lines: list[str] = []
    current_pages: list[int] = []

    def flush() -> None:
        if current_lines or current_kind == _PREAMBLE:
            pages = current_pages or [0]
            fragments.append(
                RawFragment(
                    ordinal=len(fragments),
                    lead_in=current_lead_in,
                    kind=current_kind,
                    lines=tuple(current_lines),
                    page_start=min(pages),
                    page_end=max(pages) + 1,
                )
            )

    for page, line in section_lines:
        lead_in = find_lead_in(line, markers)
        if lead_in is None:
            current_lines.append(line)
            current_pages.append(page)
        else:
            flush()
            current_kind = lead_in[0]
            current_lead_in = line.strip()
            current_lines = [line.strip()]
            current_pages = [page]

    flush()
    return fragments


def split_section(
    section_lines: Sequence[tuple[int, str]],
    *,
    markers: LeadInMarkers = TEXTBOOK_MARKERS,
    min_section_chars: int = MIN_SECTION_CHARS,
    min_fragment_chars: int = MIN_FRAGMENT_CHARS,
    min_fragments: int = MIN_FRAGMENTS,
) -> list[RawFragment]:
    """The concept-bearing fragments of one section, or `[]` to keep it whole.

    Returning `[]` is a first-class answer, not a failure: a section holding one
    definition is already the right node, and splitting it produces a child that
    duplicates its parent. A source whose author marked no boundaries returns
    `[]` for every section, which leaves the graph exactly as `toc.py` built it.
    """
    if sum(len(line) for _, line in section_lines) < min_section_chars:
        return []

    cut = _cut(section_lines, markers)

    # An `Example` is an illustration of the definition or theorem above it, not
    # a concept of its own -- it introduces no new definiendum, and the drill
    # generated from it would be indistinguishable from a drill on its parent.
    # Folding its text upward keeps the worked example available for retrieval,
    # which is the most useful passage a drill on that concept can quote.
    folded: list[RawFragment] = []
    for fragment in cut:
        if fragment.kind == _ATTACHING and folded:
            folded[-1] = _merge(folded[-1], fragment)
        elif fragment.kind == _ATTACHING:
            # An example before any definition illustrates the section's own
            # opening, so it belongs to the preamble.
            folded.append(replace(fragment, kind=_PREAMBLE, lead_in=""))
        else:
            folded.append(fragment)

    concepts = [fragment for fragment in folded if fragment.kind != _PREAMBLE]

    # Stubs merge upward. Below the floor there is not enough text to write a
    # question against, so a node here would be permanently un-drillable.
    settled: list[RawFragment] = []
    for fragment in concepts:
        if settled and len(fragment.text) < min_fragment_chars:
            settled[-1] = _merge(settled[-1], fragment)
        else:
            settled.append(fragment)

    # A leading stub had nothing above it to merge into; give it the one below.
    while len(settled) > 1 and len(settled[0].text) < min_fragment_chars:
        settled[1] = _merge(settled[0], settled[1])
        del settled[0]

    if len(settled) < min_fragments:
        return []

    pages = 1 + max(fragment.page_end for fragment in settled) - min(fragment.page_start for fragment in settled)
    ceiling = max(MAX_FRAGMENTS_FLOOR, pages * MAX_FRAGMENTS_PER_PAGE)
    if len(settled) > ceiling:
        logger.info(
            "refusing to split a %s-page section into %s fragments; the detector is over-firing",
            pages,
            len(settled),
        )
        return []

    return [replace(fragment, ordinal=index) for index, fragment in enumerate(settled)]


# ── deterministic naming ──────────────────────────────────────────────────
#
# The naming signal is NOT "the first noun after the lead-in". That was the
# first attempt and it was confidently wrong on a third of the book, because a
# definition's opening sentence contains at least two noun phrases and the
# definiendum is not reliably either one of them:
#
#     "an optimal solution is a feasible solution that maximizes ..."
#      ^ definiendum         ^ genus
#     "A directed path in G is a sequence of arcs"
#      ^ definiendum           ^ genus
#     "s in Rn is a subgradient of f at x"
#      ^ symbol                ^ definiendum
#
# So the copula is read from BOTH sides -- subject and complement are both
# candidates -- and the tie is broken by NOVELTY: the definiendum is the phrase
# the book has not already named. That is a structural fact about how textbooks
# are written (a definition introduces vocabulary; a genus reuses it), and it is
# checkable here against the titles already assigned. "A feasible solution to x
# is a Slater point of" resolves to "Slater point" because "Feasible solution"
# was defined sixty pages earlier, with no semantics and no model involved.
#
# Every gap is `\s+`, never a literal space. A PDF's lines break wherever the
# typesetter put them, so "is a\nsupporting halfspace of C" is one phrase spread
# over two lines, and a pattern spelled with spaces skips it and matches
# something incidental further down instead.

# The subject of a definitional copula: "A directed path in G is a sequence".
# Only fires on an alphabetic subject -- "s in Rn is a subgradient" has a
# symbolic subject, and the definiendum there is on the other side.
#
# At most three words, each of them a plain lowercase word. Allowing whitespace
# inside an unbounded group let it swallow a whole clause up to some later
# copula: "A graph G = (V, E) is bipartite if and only if there is a partition"
# came back as the title "Graph is bipartite if and only if there".
#
# The article is matched in both cases. Spelled `(?:The|A|An)` it silently never
# fired on a definiendum in the middle of a sentence -- "For a maximization
# problem, an optimal solution is a feasible solution that ..." -- so the whole
# subject side of the copula was dead on exactly the definitions it was written
# for, and CO 250's "Optimal solution" went to a remark three pages earlier.
# Anchored to the start of a clause -- string start, newline, or a bullet -- with
# an optional short adverbial in front of it ("For a maximization problem, an
# optimal solution is ..."). Unanchored, it took the nearest article before the
# copula rather than the sentence's subject, and "All assignment of values to
# each of the variables is a feasible solution" came back as "Variables".
_SUBJECT = re.compile(
    r"(?:^|\n)\s*[-•·*]?\s*(?:[A-Za-z][^.\n]{0,40},\s*)?"
    r"(?:[Tt]he|[Aa]n|[Aa])\s+([a-z][a-z’'-]*(?:\s+(?:[a-z][a-z’'-]*|[A-Z])){0,3}?)\s+(?:is|are)\s+(?:a|an|the)\b"
)

# The complement of the same copula: "... is a subgradient of f at x".
_COMPLEMENT = re.compile(
    r"\bis\s+(?:a|an|the)\s+([A-Za-z][A-Za-z’'-]*(?:\s+[a-z][A-Za-z’'-]*){0,3}?)"
    r"(?=\s+(?:of|if|at|for|when|that|with)\b|\s*[,.:])"
)

# Weaker patterns, tried only after the copula. Ordered strongest first.
_DEFINIENDUM = (
    # "Function f : Rn -> R is convex if", "A graph G = (V, E) is bipartite if".
    # Both groups, because the predicate alone gives "Convex" and "Bipartite",
    # which name a property rather than the object the section is about.
    re.compile(
        r"\b(?:[Tt]he|[Aa]n|[Aa])?\s*([A-Z]?[a-z]{2,20})\b[^.]{0,40}?\bis\s+([a-z][A-Za-z-]{3,24})\s+if\b"
    ),
    # "we call this a cutting plane", "is called the canonical form"
    re.compile(
        r"\b(?:call(?:ed)?|say)\s+(?:it|this|that)?\s*(?:a|an|the)\s+"
        r"([A-Za-z][A-Za-z’'\s-]{2,38}?)(?=\s*[,.:]|\s+if\b)"
    ),
    # "The halfspace F = {...} is supporting C at x" -- the sentence's subject,
    # when the predicate says something about it rather than naming it.
    re.compile(r"\b(?:[Tt]he|[Aa]n|[Aa])\s+([a-z][a-z-]{2,24}(?:\s+[a-z][a-z-]{2,24})?)\b(?=[^.]{0,80}?\bis\b)"),
    # "The epigraph of f is given by". Weakest: "the boundary of F" fits it too.
    re.compile(r"\b[Tt]he\s+([a-z][A-Za-z’'\s-]{2,38}?)\s+of\b"),
)

_TITLE_NOISE = re.compile(r"\s+")

# A one-word name from this list is furniture, not a skill: it collides with
# every other section of the book and tells a learner nothing. Only single-word
# candidates are tested against it -- "Slater point" and "Basic solution" are
# specific precisely because they are qualified.
GENERIC_NAMES = frozenset(
    """set sets type types method methods problem problems solution solutions form forms
    case cases result results value values number numbers thing things way ways example
    examples statement system element elements point points row rows column columns
    circle content contents term terms condition conditions step steps part parts idea
    and or the optimal feasible infeasible unbounded bounded translate slack above below
    following note figure table section chapter
    function functions sequence sequences variable variables expression expressions
    quantity quantities object objects collection family pair pairs list lists
    answer essence auxiliary""".split()
)


# A candidate ending in one of these is a phrase the pattern cut mid-sentence:
# "Newline that", "Distinction between", "Cone generated by". Seen on the CS 246
# ebook, where sidebar callouts have no definiendum to find.
DANGLING_WORDS = frozenset(
    """that which when where who whose what this these those and or but with by for from in
    into of on to at as if than then between among within without over under""".split()
)


def _is_generic(name: str) -> bool:
    return len(name.split()) == 1 and name.lower() in GENERIC_NAMES


def _trim_dangling(name: str) -> str:
    words = name.split()
    while words and words[-1].lower() in DANGLING_WORDS:
        words.pop()
    return " ".join(words)


def _clean_name(text: str) -> str:
    name = _TITLE_NOISE.sub(" ", text).strip(" \t-–—:.,").strip()
    if not name:
        return ""
    return name[0].upper() + name[1:]


def normalise_title(title: str) -> str:
    """The form two titles are compared in. Case, spacing and a plural `s`
    are not a distinction a learner would draw between two nodes."""
    words = [word.strip("-'’") for word in _TITLE_NOISE.sub(" ", title.lower()).split()]
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words)


def _introduced_here(name: str, fragment: RawFragment, first_mention: FirstMention) -> bool:
    """Does the book use this phrase for the first time inside this fragment?

    One page of slack, because a section often motivates a term in the sentence
    immediately above the `Definition` that pins it down.
    """
    page = first_mention.page_of(name)
    return page is None or page >= fragment.page_start - FIRST_MENTION_SLACK_PAGES


def _acceptable(name: str, markers: LeadInMarkers) -> bool:
    # A lead-in word extracted from the prose is the worst possible title:
    # "Remarks:" over a passage saying "the definition of" yields a node called
    # "Definition". Seen on STAT 231.
    return len(name) >= 3 and not _is_generic(name) and markers.kind_for(name) is None


class FirstMention:
    """Where each phrase first appears in the document.

    A book introduces a term where it defines it. So a phrase pulled out of a
    fragment's prose is that fragment's subject only if the book had not already
    been using it: "subgradient" first appears on the page that defines it,
    while "answer", "essence", "auxiliary" and "boundary" were in use long
    before the passage a pattern scraped them from.

    This is the signal that separates a definiendum from an incidental noun
    without a stop-list, without semantics and without a model. It is also the
    reason a lead-in's EXPLICIT name is exempt: when the author writes
    `Definition: cut`, they have already told us, and the word may well have
    appeared in the motivating paragraph above.
    """

    def __init__(self, page_texts: Sequence[str]) -> None:
        self._pages: list[int] = []
        self._text = ""
        parts: list[str] = []
        offset = 0
        for index, text in enumerate(page_texts):
            lowered = " " + _TITLE_NOISE.sub(" ", text.lower()) + " "
            parts.append(lowered)
            self._pages.append(offset)
            offset += len(lowered)
        self._text = "".join(parts)

    def page_of(self, phrase: str) -> int | None:
        found = self._text.find(f" {phrase.lower().strip()} ")
        if found < 0:
            return None
        return bisect_right(self._pages, found) - 1


def title_candidates(
    fragment: RawFragment,
    markers: LeadInMarkers = TEXTBOOK_MARKERS,
    first_mention: FirstMention | None = None,
) -> list[str]:
    """Every name the BOOK supports for this fragment, strongest first.

    A list rather than one answer, because choosing between them needs to know
    what the book has already named -- which is a property of the document, not
    of the fragment. `_assign_titles` applies that.
    """
    candidates: list[str] = []

    def offer(raw: str, *, gated: bool = False) -> None:
        name = _trim_dangling(_clean_name(raw))
        if not _acceptable(name, markers) or name in candidates:
            pass
        elif len(name.split()) > MAX_TITLE_WORDS:
            pass
        elif gated and first_mention is not None and not _introduced_here(name, fragment, first_mention):
            pass
        else:
            candidates.append(name)

    lead_in = fragment.lead_in.strip()
    match = _KEYWORD_LEAD_IN.match(lead_in)
    if match is not None and markers.kind_for(match.group("word")) is not None:
        offer(match.group("name") or "")
    elif fragment.kind == "named":
        offer(lead_in)

    # Only the opening. A definition names its subject in its first sentence or
    # two; further down sit the worked example and the proof, which mention
    # every neighbouring concept and produce confidently wrong names -- the
    # supporting-halfspace definition ends "x is on the boundary of F", and a
    # whole-body search titles it "Boundary".
    body = fragment.body[:DEFINIENDUM_SEARCH_CHARS]

    subject = _SUBJECT.search(body)
    if subject is not None:
        offer(subject.group(1))
    complement = _COMPLEMENT.search(body)
    if complement is not None:
        offer(complement.group(1))

    # The weak patterns are for DEFINING passages only. They exist to catch
    # "The epigraph of f is given by" and "Function f is convex if", which have
    # no copula to read -- but on a `Remark`, which states a result about things
    # already named, the same patterns have nothing to find and return the
    # nearest noun instead: "Auxiliary", "Boundary", "Answer". The author's own
    # label decides how much benefit of the doubt a passage gets.
    if fragment.kind in DEFINING_KINDS:
        for pattern in _DEFINIENDUM:
            found = pattern.search(body)
            if found is not None:
                # A two-group pattern captures (subject, property) and reads
                # backwards: "graph ... is bipartite" is "Bipartite graph".
                parts = [group for group in found.groups() if group]
                offer(" ".join(reversed(parts)) if len(parts) > 1 else parts[0], gated=True)

    return candidates


def fallback_title(fragment: RawFragment, section_title: str) -> str:
    """Used when the book supports no name this document has not already taken.

    Deliberately plain rather than plausible. A learner reading "Cutting Planes
    (Remark 4)" knows they are looking at the section's fourth remark; a learner
    reading a confidently wrong "Optimal solution" does not know anything is
    amiss, and neither does any checker.

    Parenthesised, not "Section: Remark 4". `prereqs.py` renders each skill as
    ``- `slug` — Title: summary`` and its matcher reads the title as everything
    before the first colon, so a colon inside a title silently truncates it to
    the section name -- which then matches every section that mentions the
    section. One such node on CS 246 was worth 137 spurious inferred edges.
    """
    label = _clean_name(fragment.lead_in.strip()) or "Concept"
    return f"{section_title} ({label} {fragment.ordinal + 1})"


def structural_title(
    fragment: RawFragment,
    section_title: str,
    markers: LeadInMarkers = TEXTBOOK_MARKERS,
    claimed_titles: Container[str] = frozenset(),
    first_mention: FirstMention | None = None,
) -> str:
    """The best title derivable from the book alone, with no model.

    Used for the fragment's SLUG in every case, and for its display title when
    the model declines or returns something generic. Deriving the slug
    structurally rather than from the model's wording is what keeps slugs -- and
    therefore a learner's EXP and review history -- stable across re-ingests of
    the same book with a different model behind the naming role.
    """
    for candidate in title_candidates(fragment, markers, first_mention):
        if normalise_title(candidate) not in claimed_titles:
            return candidate
    return fallback_title(fragment, section_title)


def _is_usable_title(title: str, fragment: RawFragment, markers: LeadInMarkers) -> bool:
    """Reject a model title that is just the lead-in word again.

    "Definition" and "Remark 1" are labels, not skills; a tree full of them is
    the failure this module exists to avoid.
    """
    cleaned = title.strip()
    if not (2 <= len(cleaned) <= 80):
        return False
    match = _KEYWORD_LEAD_IN.match(cleaned)
    if match is not None and markers.kind_for(match.group("word")) is not None:
        return bool((match.group("name") or "").strip())
    return cleaned.lower() != fragment.lead_in.strip().lower() or fragment.kind == "named"


# ── naming through the LLM seam ───────────────────────────────────────────


def render_fragments(fragments: Sequence[RawFragment], limit: int = FRAGMENT_PROMPT_CHARS) -> str:
    """The fragment listing the naming prompt shows the model.

    Machine-parseable on purpose: the deterministic provider reads the same
    rendering the real one does, so the fake exercises the real code path rather
    than a shortcut around it.
    """
    blocks: list[str] = []
    for fragment in fragments:
        label = fragment.lead_in or "(section opening)"
        blocks.append(f"[fragment {fragment.ordinal}] lead-in: {label}\n{fragment.text[:limit]}")
    return "\n\n".join(blocks)


def _apply_model_names(
    fragments: list[RawFragment], returned: list[dict], outcome: SegmentOutcome
) -> tuple[list[RawFragment], dict[int, tuple[str, str, tuple[str, ...]]]]:
    """Fold `standalone: false` fragments and collect titles by ordinal.

    A model may only remove a boundary here. Nothing it returns can create one:
    the fragment list it is answering about was already fixed by `split_section`.
    """
    by_ordinal: dict[int, dict] = {}
    for item in returned:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(fragments):
            by_ordinal[index] = item

    kept: list[RawFragment] = []
    names: dict[int, tuple[str, str, tuple[str, ...]]] = {}
    for fragment in fragments:
        item = by_ordinal.get(fragment.ordinal)
        standalone = True if item is None else bool(item.get("standalone", True))
        if not standalone and kept:
            kept[-1] = _merge(kept[-1], fragment)
            outcome.fragments_merged_by_model += 1
        else:
            kept.append(fragment)
            if item is not None:
                title = str(item.get("title", "")).strip()
                summary = str(item.get("summary", "")).strip()
                terms = tuple(str(term).strip() for term in item.get("key_terms", []) if str(term).strip())
                names[fragment.ordinal] = (title, summary, terms[:6])

    return kept, names


def _name_fragments(
    client: LLMClient | None,
    book_title: str,
    section: SectionInput,
    fragments: list[RawFragment],
    outcome: SegmentOutcome,
    course_id: str | None,
) -> tuple[list[RawFragment], dict[int, tuple[str, str, tuple[str, ...]]]]:
    if client is None:
        return fragments, {}

    try:
        result = run_sync(
            client.structured(
                LLMRole.SECTION_SEGMENT,
                {
                    "book_title": book_title,
                    "section_title": section.title,
                    "section_slug": section.slug,
                    "fragment_count": len(fragments),
                    "fragments": render_fragments(fragments),
                },
                course_id=course_id,
            )
        )
    except (SchemaValidationError, RefusalError) as exc:
        # Absorbed per section, exactly as window extraction and prerequisite
        # inference are. Structural titles are a real fallback, not a
        # placeholder, so losing the naming call costs polish and not the split.
        outcome.sections_naming_failed += 1
        logger.warning("fragment naming failed for %s: %s", section.slug, exc)
        return fragments, {}

    outcome.sections_named += 1
    return _apply_model_names(fragments, list(result.data.get("fragments", [])), outcome)


def _chunks_for(section: SectionInput, page_start: int, page_end: int) -> tuple[uuid.UUID, ...]:
    """Provenance: every chunk whose pages overlap the fragment's pages.

    Falls back to the whole section's chunks. A node with no source chunks
    cannot be drilled at all -- question generation has nothing to retrieve
    against -- so a coarse answer beats an empty one.
    """
    overlapping = tuple(
        chunk.id for chunk in section.chunks if chunk.page_start < page_end and chunk.page_end >= page_start
    )
    return overlapping or tuple(chunk.id for chunk in section.chunks)


def segment_sections(
    sections: Sequence[SectionInput],
    page_texts: Sequence[str],
    *,
    client: LLMClient | None = None,
    book_title: str = "",
    course_id: str | None = None,
    claimed_slugs: set[str] | None = None,
    claimed_titles: set[str] | None = None,
    markers: LeadInMarkers = TEXTBOOK_MARKERS,
) -> SegmentOutcome:
    """Sub-section concepts for every section that has more than one.

    `claimed_slugs` is the same set `_toc_graph` already threads through for
    cross-document slug collisions; fragment slugs are added to it so two books
    in one course cannot collide. `claimed_titles` does the same for *titles*,
    in `normalise_title` form, and is seeded from the section titles here when
    the caller does not supply one.

    **No two nodes may end up with the same title.** Two nodes called "Optimal
    solution" are not a cosmetic problem: a learner cannot tell them apart, and
    every downstream pass that matches skills by name -- prerequisite inference
    above all -- fires once per duplicate on every mention in the book. On
    CO 250 five duplicate-titled fragments alone accounted for 143 of 474
    inferred edges.

    `client=None` runs the whole pass with structural titles and no LLM call at
    all, which is what the unit tests use.
    """
    outcome = SegmentOutcome()
    if not sections or not page_texts:
        return outcome

    claimed = claimed_slugs if claimed_slugs is not None else set()
    titles = claimed_titles if claimed_titles is not None else set()
    # The outline's own titles are taken before any fragment is named. A section
    # is already a node; a child repeating its name is not a second concept.
    titles.update(normalise_title(section.title) for section in sections)
    spans = section_line_spans(sections, page_texts)
    first_mention = FirstMention(page_texts)

    prepared: list[tuple[SectionInput, list[RawFragment], dict[int, tuple[str, str, tuple[str, ...]]]]] = []
    for section in sections:
        outcome.sections_seen += 1
        raw = split_section(spans.get(section.slug, []), markers=markers)
        if not raw:
            outcome.sections_kept_whole += 1
        else:
            raw, names = _name_fragments(client, book_title, section, raw, outcome, course_id)
            if len(raw) < MIN_FRAGMENTS:
                # The model folded the section back into one concept.
                outcome.sections_kept_whole += 1
            else:
                prepared.append((section, raw, names))

    chosen = _assign_titles(prepared, titles, markers, first_mention)

    for section, raw, names in prepared:
        built = _build_section(section, raw, names, chosen, claimed, titles, markers, first_mention, outcome)
        if len(built) < MIN_FRAGMENTS:
            # Every fragment turned out to be the section itself restated.
            outcome.sections_kept_whole += 1
            for fragment in built:
                claimed.discard(fragment.slug)
        else:
            outcome.sections_split += 1
            outcome.fragments[section.slug] = built
            outcome.fragments_total += len(built)

    return outcome


# A `Definition` or a `Theorem` INTRODUCES a term; a `Remark` that mentions the
# same term is talking about it. The book draws that distinction itself, on the
# lead-in line, and it is the tie-breaker novelty alone cannot supply: CO 250's
# shortest-path remark on page 19 says "if x is an optimal solution for the
# above IP", four pages before section 2.1 actually defines "optimal solution".
# First-come naming gave the term to the remark and pushed the real definition
# onto a fallback -- and that one mis-claim was worth 28 spurious inferred edges.
DEFINING_KINDS = frozenset(
    """definition theorem lemma corollary proposition named axiom notation property
    algorithm procedure""".split()
)


def _assign_titles(
    prepared: Sequence[tuple[SectionInput, list[RawFragment], dict]],
    titles: set[str],
    markers: LeadInMarkers,
    first_mention: FirstMention,
) -> dict[tuple[str, int], str]:
    """Choose one structural title per fragment, definitions first.

    Two passes over the whole document rather than one pass per section,
    because "has anything already named this?" is a question about the book and
    not about the section. Reservations made here are consumed in `_build`.
    """
    chosen: dict[tuple[str, int], str] = {}

    def claim(only_defining: bool) -> None:
        for section, raw, _ in prepared:
            for fragment in raw:
                key = (section.slug, fragment.ordinal)
                defining = fragment.kind in DEFINING_KINDS
                if key in chosen or defining is not only_defining:
                    pass
                else:
                    for candidate in title_candidates(fragment, markers, first_mention):
                        if normalise_title(candidate) not in titles:
                            titles.add(normalise_title(candidate))
                            chosen[key] = candidate
                            break

    claim(only_defining=True)
    claim(only_defining=False)
    return chosen


_RECALL = re.compile(r"\b(?:recall|as (?:we )?(?:saw|noted)|previously|again)\b", re.IGNORECASE)
_RECALL_SEARCH_CHARS = 160


def _build_section(
    section: SectionInput,
    raw: list[RawFragment],
    names: dict[int, tuple[str, str, tuple[str, ...]]],
    chosen: dict[tuple[str, int], str],
    claimed: set[str],
    titles: set[str],
    markers: LeadInMarkers,
    first_mention: FirstMention,
    outcome: SegmentOutcome,
) -> list[Fragment]:
    """Name, de-duplicate and emit one section's fragments.

    Three outcomes per fragment, decided here rather than in `_build` because
    each one needs to see what the rest of the document has already claimed:

    * **emit** -- the book supports a name nothing else has taken;
    * **suppress** -- the fragment's strongest name is the SECTION's own name,
      so it is the section's core definition. The section node already carries
      that title and already owns these chunks by page, so emitting a child
      duplicates its parent and loses nothing when dropped. This is what keeps
      `partial-derivative` a single node;
    * **merge** -- the book explicitly says it is restating ("Recall that ...")
      something already named. Its chunks and pages are added to the node that
      owns the name, so the restatement becomes extra provenance for the concept
      rather than a second node for it.

    Anything else with no free name falls back to `Section: Remark 4`, which is
    unique by construction and, unlike a plausible wrong name, is legible as a
    gap to both a learner and a checker.
    """
    emitted: list[Fragment] = []
    by_title: dict[str, int] = {}
    section_title = normalise_title(section.title)

    for fragment in raw:
        # Ungated: this list is only asked "is this fragment the section
        # itself?", which is a question about identity, not about novelty.
        candidates = title_candidates(fragment, markers)
        reserved = chosen.get((section.slug, fragment.ordinal))

        if candidates and normalise_title(candidates[0]) == section_title:
            outcome.fragments_are_the_section += 1
        elif reserved is None and candidates and _RECALL.search(fragment.body[:_RECALL_SEARCH_CHARS]):
            # Only into the fragment immediately above. Merging into anything
            # further back stretches that node's page range forward over every
            # concept in between, and a page-homed reader then cannot see them:
            # CO 250's page 36 "Recall that ... B is an optimal basis" merged
            # back to page 32 and swallowed the whole simplex-optimality section.
            target = by_title.get(normalise_title(candidates[0]))
            if target != len(emitted) - 1:
                target = None
            if target is None:
                emitted.append(_build(section, fragment, names.get(fragment.ordinal), reserved, claimed, titles, markers))
            else:
                emitted[target] = _absorb(emitted[target], fragment, section)
                outcome.fragments_merged_as_restatement += 1
        else:
            built = _build(section, fragment, names.get(fragment.ordinal), reserved, claimed, titles, markers)
            by_title.setdefault(normalise_title(built.title), len(emitted))
            emitted.append(built)

    return emitted


def _absorb(node: Fragment, restatement: RawFragment, section: SectionInput) -> Fragment:
    """Fold a restatement into the node that already names the concept."""
    page_start = min(node.page_start, restatement.page_start)
    page_end = max(node.page_end, restatement.page_end)
    return replace(
        node,
        text=f"{node.text}\n\n{restatement.text}",
        page_start=page_start,
        page_end=page_end,
        source_chunk_ids=tuple(
            dict.fromkeys(node.source_chunk_ids + _chunks_for(section, restatement.page_start, restatement.page_end))
        ),
    )


def _fallback_summary(title: str, text: str) -> str:
    """A readable caption for a fragment the namer did not summarise.

    Head-truncating the body is the same defect `summarise` was written to fix,
    one level down: it captions a fragment with whatever its first 280 characters
    happen to be, which on a textbook is routinely a different concept. At
    section level that had "The KKT Theorem" described as an epigraph and
    "Strong Duality" described by the *weak* duality theorem.

    Imported inside the function because `summarise` imports this module for its
    lead-in detection, so a module-level import here would be circular. The
    dependency is genuinely one-directional in spirit -- summarise is the
    higher-level module -- and this is the one call that runs the other way.
    """
    from app.ingestion import summarise

    return summarise.section_summary(title, text)


def _build(
    section: SectionInput,
    fragment: RawFragment,
    named: tuple[str, str, tuple[str, ...]] | None,
    reserved: str | None,
    claimed: set[str],
    titles: set[str],
    markers: LeadInMarkers,
) -> Fragment:
    # `reserved` is this fragment's structural title, already chosen against the
    # whole document by `_assign_titles`. None means the book supported no name
    # nothing else had taken.
    structural = reserved or fallback_title(fragment, section.title)
    title = structural
    summary = ""
    terms: tuple[str, ...] = ()

    if named is not None:
        model_title, model_summary, model_terms = named
        # The model is held to the same uniqueness rule as the namer. Nothing
        # stops it returning a title another section already used.
        usable = _is_usable_title(model_title, fragment, markers)
        if usable and normalise_title(model_title) not in titles:
            title = model_title
        summary = model_summary
        terms = model_terms

    titles.add(normalise_title(title))

    # Trimmed so the de-duplicating suffix still fits: `slugify` caps at 64, and
    # appending "-2" afterwards pushed a STAT 231 fragment to 65 characters,
    # which the prereq-edge schema rejects -- silently losing that section's
    # inferred edges with an error naming only the slug.
    base = slugify(structural)[:MAX_SLUG_CHARS] or f"{section.slug}-{fragment.ordinal + 1}"
    base = base.strip("-") or f"{section.slug}-{fragment.ordinal + 1}"
    slug = base
    suffix = 2
    while slug in claimed:
        slug = f"{base}-{suffix}"
        suffix += 1
    claimed.add(slug)

    return Fragment(
        parent_slug=section.slug,
        slug=slug,
        title=title,
        summary=summary or _fallback_summary(title, fragment.text) or title,
        lead_in=fragment.lead_in,
        kind=fragment.kind,
        text=fragment.text,
        page_start=fragment.page_start,
        page_end=fragment.page_end,
        # The fragment IS the section's material, not a more specialised branch
        # of it, so it inherits the section's difficulty rather than gaining a
        # level's worth. Splitting a node must not make its content harder.
        difficulty=section.difficulty,
        level=section.level + 1,
        source_chunk_ids=_chunks_for(section, fragment.page_start, fragment.page_end),
        key_terms=terms,
        named_by_model=named is not None and title != structural,
    )
