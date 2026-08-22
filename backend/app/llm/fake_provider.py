"""Deterministic provider. The default, so it has to be genuinely useful.

Not a stub returning canned constants. It derives its output from the actual
input, which means:

* the graph a fake ingest produces has real structure drawn from real headings,
  so the tree renders and the layout code is exercised;
* the fake grader scores by rubric overlap, so a good answer really does score
  higher than gibberish -- without that, the entire drill/EXP/SRS loop is
  untestable and every test would be asserting against a constant.

Same input always yields the same output, so tests never flake.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any, AsyncIterator, Mapping, Sequence

from app.config import get_settings
from app.llm.base import LLMRole, StreamDelta, StructuredResult, Usage
from app.llm.support import prepare, validate_or_raise

STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the their then there
    these this to was were which with you your we our can will not but if when each other than them
    they how what where who why all any some more most such only own same so too very just also both
    one two three first second new use used using make makes made get gets give given take taken""".split()
)

WORD = re.compile(r"[A-Za-z][A-Za-z-]{2,}")

# The words `_question` uses to frame a rubric point, plus the `(weight N)`
# suffix `_render_rubric` appends. They carry no meaning, so a grader that
# counts them as required content makes the rubric unanswerable: a point reading
# "Explains the role of direction in Vectors. (weight 0.5)" would demand five
# words of which only one -- "direction" -- is the thing actually being tested.
RUBRIC_SCAFFOLD = frozenset("explains explain role weight point key states describes mentions".split())

# `kp1: <point text> (weight 0.5)`, the shape `drill_service._render_rubric` emits.
RUBRIC_LINE = re.compile(r"^\s*(kp[0-9]+)\s*:\s*(.*?)\s*(?:\(weight[^)]*\))?\s*$", re.IGNORECASE)

# `[fragment 3] lead-in: Definition: Subgradient`, the shape
# `app.ingestion.segment.render_fragments` emits, followed by that fragment's text.
SEGMENT_FRAGMENT = re.compile(
    r"^\[fragment (\d+)\] lead-in: ([^\n]*)\n(.*?)(?=^\[fragment \d+\] lead-in:|\Z)",
    re.M | re.S,
)
# The part of a lead-in after `:` or a dash -- the name the author already wrote.
SEGMENT_LEAD_IN_NAME = re.compile(r"^[A-Za-z]+\s*\d*(?:\.\d+)*\s*[:–—-]\s*(\S.*)$")


def _stem(word: str) -> str:
    """Crude plural fold, so an answer saying "vector" satisfies a point that
    happens to say "vectors". A real grader handles this by understanding the
    sentence; a word-overlap fake has to be told."""
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64].strip("-") or "concept"


def _seeded_unit_interval(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _salient_terms(text: str, limit: int, exclude: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Frequent, non-trivial words -- a crude but deterministic concept proxy."""
    counts: dict[str, int] = {}
    for match in WORD.finditer(text):
        word = match.group(0).lower()
        if word not in STOPWORDS and len(word) > 3 and _stem(word) not in exclude:
            counts[word] = counts.get(word, 0) + 1
    # Sort by frequency then alphabetically, so ties are stable.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]


# ── lexical cues, shared by both prerequisite roles ──────────────────────
#
# The old prerequisite fake fired only when a section printed another skill's
# title verbatim. Real prose does not do that: it writes "since A_B is
# invertible", never "Inverse of a Matrix". So the fake systematically missed
# exactly the foundational skills, and the measured recall was partly the fake's
# ceiling rather than the pipeline's. What follows is still a word matcher --
# deterministic, and refusing to emit anything it cannot quote -- but one that
# recognises a skill by its vocabulary as well as by its title.

CUE_STEM_PREFIX = 5
CUE_MIN_TERM_LEN = 7
CUE_MIN_TERM_COUNT = 2
CUE_LONG_TERM_LEN = 9
CUE_DF_RATIO = 0.25
CUE_MAX_TERMS = 4
CUE_THRESHOLD = 0.9
CUE_TITLE_WEIGHT = 1.0
# Weights are deliberately set so that only the verbatim title fires on a single
# sighting. Everything weaker has to be SAID TWICE, or corroborated by a second
# cue, before it reaches CUE_THRESHOLD. Measured on CO 250, letting a single
# proximity match fire took precision from 0.59 to 0.43 and tripled the number
# of backwards edges: a book that writes "we will introduce the Certificate of
# Optimality" is forward-referencing, not depending, and one sighting cannot
# tell those apart.
CUE_PROXIMITY_WEIGHT = 0.45
CUE_PROXIMITY_WINDOW = 30
CUE_TERM_WEIGHT = 0.4
CUE_MAX_REPEAT = 2
CUE_QUOTE_CHARS = 300
CUE_MAX_DEPENDENTS = 8

# Words a title uses to join its content words. Dropping them is what lets
# "Inverse of a Matrix" be recognised as {inverse, matrix}.
TITLE_FILLER = frozenset("a an the of for and or in on to with as by its".split())

# The title is read back from between the bold markers, NOT up to the first
# colon. A colon-separated title truncated "Formulations: Overview" to
# "Formulations", which then matched every section in that chapter. See
# `prereqs._render_skill_list`; the two must change together.
SKILL_LINE = re.compile(r"^-\s*`([a-z0-9-]+)`\s*—\s*\*\*(.+?)\*\*\s*—\s*(.*)$")
CANDIDATE_HEAD = re.compile(r"^###\s*`([a-z0-9-]+)`\s*—\s*(.+)$", re.M)

# (kind, words, weight). kind is "phrase" | "proximity" | "term".
Cue = tuple[str, tuple[str, ...], float]
# (lowercased single-spaced text, folded word -> offsets in it, original text).
Haystack = tuple[str, dict[str, list[int]], str]


def _fold(word: str) -> str:
    """Crude morphological fold: lowercase, then truncate to a prefix.

    "invertible"/"inverse" -> "inver", "independent"/"independence" -> "indep",
    "linearly"/"linear" -> "linea", "convexity"/"convex" -> "conve". Prose names
    a foundation by its adjective, not by the title of the section that defined
    it, so a matcher that cannot cross that boundary is blind to precisely the
    edges the prerequisite passes exist to find.

    Crude enough to collide ("constant"/"constraint"), which is why a folded
    term also has to be long and rare before it is allowed to count.
    """
    return word.lower()[:CUE_STEM_PREFIX]


def _fold_positions(text: str) -> dict[str, list[int]]:
    """Index every folded word, and each part of a hyphenated compound.

    `WORD` keeps hyphens, so "sub-matrix" is one token and folds to "sub-m" --
    which is how a matcher looking for "matrix" misses the sentence "AB is a
    columns sub-matrix of A". Indexing the parts as well is not a loosening: the
    word really is there.
    """
    positions: dict[str, list[int]] = {}
    for match in WORD.finditer(text):
        token = match.group(0)
        parts = [token] + (token.split("-") if "-" in token else [])
        for folded in {_fold(part) for part in parts if len(part) >= 3}:
            positions.setdefault(folded, []).append(match.start())
    return positions


def _prepare(text: str) -> Haystack:
    """Fold a passage once, so scoring N skills against it stays linear."""
    normalized = " ".join(text.split()).lower()
    return (normalized, _fold_positions(normalized), normalized)


def _document_frequency(texts: Sequence[str]) -> dict[str, int]:
    """How many of these passages each folded word appears in.

    Computed from the contents of the prompt itself, so the fake never reads
    anything it was not shown -- which is what keeps it a stand-in for a reader
    rather than a lookup table with privileged access.
    """
    frequency: dict[str, int] = {}
    for text in texts:
        for folded in _fold_positions(text):
            frequency[folded] = frequency.get(folded, 0) + 1
    return frequency


def _proximity_hits(words: tuple[str, ...], positions: dict[str, list[int]]) -> list[int]:
    """Offsets where all of `words` occur within one window.

    Proximity rather than "all present somewhere in the section": a 5000-word
    chapter contains almost any pair of common words *somewhere*, so a
    document-wide conjunction fires on subject matter rather than on use. Two
    title words standing next to each other is a phrase; the same two words five
    pages apart is a coincidence.
    """
    occurrences = [positions.get(word, []) for word in words]
    if not all(occurrences):
        return []

    anchor = min(range(len(words)), key=lambda i: len(occurrences[i]))
    return [
        at
        for at in occurrences[anchor]
        if all(
            any(abs(other - at) <= CUE_PROXIMITY_WINDOW for other in spots)
            for index, spots in enumerate(occurrences)
            if index != anchor
        )
    ]


def _window(text: str, at: int, length: int) -> str:
    """A quotation around a hit. The schemas require at least 10 characters."""
    snippet = " ".join(text[max(0, at - 50) : at + length + 60].split())[:CUE_QUOTE_CHARS]
    return snippet if len(snippet) >= 10 else f"{snippet} (from the section text)"[:CUE_QUOTE_CHARS]


def _skill_cues(
    title: str,
    defining_text: str,
    frequency: dict[str, int],
    corpus: int,
    *,
    terms: bool = False,
) -> list[Cue]:
    """What to look for when asking whether a passage uses this skill.

    Three kinds, in descending strength: the title said verbatim; the title's
    content words together in one window under the morphological fold; and terms
    distinctive to the skill's own defining text.

    `terms` is off by default, and the reason is the whole point of the reverse
    role. "Distinctive" only means something when there is a corpus to measure it
    against. The forward prompt carries 110 characters of summary per skill, over
    which almost every word looks rare, so a term cue there fires on subject
    matter and destroys precision -- measured on CO 250 it took precision from
    0.59 to 0.09. The reverse prompt carries whole excerpts of every candidate,
    so document frequency there separates "invertible" from "matrix", and the
    term cues earn their place.
    """
    cues: list[Cue] = []
    phrase = " ".join(title.split()).lower()
    if len(phrase) >= 6:
        cues.append(("phrase", (phrase,), CUE_TITLE_WEIGHT))

    title_folds = tuple(
        dict.fromkeys(_fold(m.group(0)) for m in WORD.finditer(title) if m.group(0).lower() not in TITLE_FILLER)
    )
    if len(title_folds) >= 2:
        cues.append(("proximity", title_folds, CUE_PROXIMITY_WEIGHT))

    if terms:
        cues.extend(_term_cues(defining_text, frequency, corpus))

    return cues


def _term_cues(defining_text: str, frequency: dict[str, int], corpus: int) -> list[Cue]:
    """Long words the source leans on that the rest of the corpus does not.

    A word the whole book uses -- "matrix", "solution", "problem" -- is worthless
    as a cue and is dropped. That filter is the difference between recognising a
    skill and recognising its subject matter.

    Words that share a stem with the title are deliberately NOT excluded here,
    even though the proximity cue may also match them. Excluding them was tried
    and it is exactly wrong: the single best evidence that a passage relies on
    "Inverse of a Matrix" is the word "invertible", and folding it away as
    "already covered by the title" left the cue list holding "calculate",
    "determine" and "satisfies" -- the section's filler instead of its subject.
    """
    ceiling = max(1, int(corpus * CUE_DF_RATIO))
    words: dict[str, int] = {}
    for match in WORD.finditer(defining_text):
        word = match.group(0).lower()
        if len(word) >= CUE_MIN_TERM_LEN and word not in STOPWORDS:
            words[word] = words.get(word, 0) + 1

    ranked = sorted(
        (
            (count, word)
            for word, count in words.items()
            if (count >= CUE_MIN_TERM_COUNT or len(word) >= CUE_LONG_TERM_LEN)
            and frequency.get(_fold(word), 0) <= ceiling
        ),
        key=lambda pair: (-pair[0], pair[1]),
    )

    chosen: list[str] = []
    for _, word in ranked:
        folded = _fold(word)
        if folded in chosen:
            pass  # a different surface form of a term already chosen
        elif len(chosen) < CUE_MAX_TERMS:
            chosen.append(folded)

    return [("term", (folded,), CUE_TERM_WEIGHT) for folded in chosen]


def _score_cues(cues: list[Cue], haystack: Haystack) -> tuple[float, str]:
    """Total weight of the cues this passage contains, plus the best quotation.

    A repeated distinctive term counts twice: "maximal set of independent
    columns", said three times, is a section leaning on linear independence,
    where saying it once may be a coincidence. No single term cue can reach the
    firing threshold on its own -- two independent ones must agree.
    """
    lowered, positions, _original = haystack
    score = 0.0
    best_gain, best_quote = 0.0, ""

    for kind, words, weight in cues:
        if kind == "phrase":
            at = lowered.find(words[0])
            hits, length = (1 if at >= 0 else 0), len(words[0])
        elif kind == "proximity":
            spots = _proximity_hits(words, positions)
            at, hits, length = (spots[0] if spots else -1), len(spots), CUE_PROXIMITY_WINDOW
        else:
            spots = positions.get(words[0], [])
            at, hits, length = (spots[0] if spots else -1), len(spots), CUE_STEM_PREFIX

        gained = weight * min(hits, CUE_MAX_REPEAT)
        score += gained
        if gained > best_gain:
            best_gain, best_quote = gained, _window(lowered, at, length)

    return round(score, 3), best_quote


def _cue_confidence(score: float) -> float:
    """Never certain, never below either pass's floor, monotone in the evidence."""
    return round(min(0.85, 0.55 + 0.1 * score), 3)


def _parse_skill_list(listing: str) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    for line in listing.splitlines():
        match = SKILL_LINE.match(line)
        if match is None:
            pass
        else:
            parsed.append((match.group(1), match.group(2).strip(), match.group(3).strip()))
    return parsed


def _parse_candidates(block: str) -> list[tuple[str, str, str]]:
    """Read back the `### \\`slug\\` — Title` blocks the reverse prompt renders."""
    heads = list(CANDIDATE_HEAD.finditer(block))
    return [
        (
            head.group(1),
            head.group(2).strip(),
            block[head.end() : heads[i + 1].start() if i + 1 < len(heads) else len(block)].strip(),
        )
        for i, head in enumerate(heads)
    ]


# `### \`slug\` — Title` / `node_id:` / `chunk_id:` / the passage, which is what
# `qa_service._render_passages` emits. The fake reads back the shipping
# rendering rather than a shortcut, so a change to the prompt's wire format
# breaks a test instead of silently degrading the answer.
PASSAGE_BLOCK = re.compile(
    r"^###\s*`([a-z0-9-]+)`\s*—\s*(.+?)\n\s*node_id:\s*(\S+)\n\s*chunk_id:\s*(\S+)\n(.*?)(?=^###\s*`|\Z)",
    re.M | re.S,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
# Below this a "sentence" is a fragment, and the summary schema's 20-character
# floor would reject the whole batch over it.
MIN_FAKE_SENTENCE = 15


def _parse_passages(block: str) -> list[tuple[str, str, str, str, str]]:
    """(slug, title, node_id, chunk_id, text) per retrieved passage."""
    return [
        (m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4).strip(), m.group(5).strip())
        for m in PASSAGE_BLOCK.finditer(block)
    ]


def _first_sentence_naming(text: str, words: Sequence[str]) -> str:
    """The first sentence containing every one of `words`, or `""`.

    Returning `""` is a real answer: an excerpt that never mentions what its own
    node is called cannot be captioned from a word matcher, and guessing would
    reproduce the bug this role exists to fix.
    """
    sentences = [s.strip() for s in SENTENCE.split(" ".join(text.split())) if s.strip()]
    for sentence in sentences:
        lowered = sentence.lower()
        if len(sentence) >= MIN_FAKE_SENTENCE and all(word in lowered for word in words):
            return sentence
    return ""


# @spec LLM-FAKE-003, LLM-FAKE-004, LLM-FAKE-008
class FakeLLMClient:
    """Implements app.llm.base.LLMClient."""

    provider = "fake"
    model = "fake"

    def model_for(self, role: LLMRole) -> str:
        return self.model

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        if role is LLMRole.QUESTION_GEN and "requested_type" not in variables:
            variables = {**variables, "requested_type": "short_answer"}
        call = prepare(role, variables, self.model)

        builders = {
            LLMRole.GRAPH_EXTRACT_MAP: self._extract,
            LLMRole.GRAPH_MERGE: self._merge,
            LLMRole.PREREQ_INFER: self._prereq_infer,
            LLMRole.PREREQ_DEPENDENTS: self._prereq_dependents,
            LLMRole.SECTION_SEGMENT: self._section_segment,
            LLMRole.NODE_SUMMARY: self._node_summary,
            LLMRole.CAMPAIGN_OUTCOME_EVAL: self._campaign_outcome_eval,
            LLMRole.CURRICULUM_PLAN: self._curriculum_plan,
            LLMRole.COURSE_QA: self._course_qa,
            LLMRole.QUESTION_GEN: self._question,
            LLMRole.GRADE: self._grade,
            LLMRole.PERFORMANCE_FEEDBACK: self._performance_feedback,
            LLMRole.SCORE_COMPOSE: self._score_compose,
            LLMRole.LIVE_COACH_CUE: self._live_coach_cue,
        }
        data = builders[role](variables)
        validate_or_raise(data, call.schema)

        return StructuredResult(
            data=data,
            raw_text="<fake>",
            model=self.model,
            provider=self.provider,
            prompt_id=call.config.prompt_id,
            prompt_version=call.config.prompt_version,
            prompt_sha256=call.prompt_sha256,
            request_fingerprint=call.request_fingerprint,
            usage=Usage(
                input_tokens=len(call.prompt_text) // 4,
                output_tokens=64,
                cost_usd=Decimal(0),
            ),
        )

    # ── per-role builders ────────────────────────────────────────────────

    def _extract(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        chunks = str(variables.get("chunks", ""))
        section_path = str(variables.get("section_path", "")) or "section"

        terms = _salient_terms(chunks, limit=4)
        if not terms:
            terms = [_slugify(section_path)]

        concepts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, term in enumerate(terms):
            slug = _slugify(term)
            if slug not in seen:
                seen.add(slug)
                concepts.append(
                    {
                        "slug": slug,
                        "title": term.replace("-", " ").title(),
                        "summary": f"Understand and apply {term} as presented in {section_path}.",
                        "difficulty": 1 + (index % 5),
                        "assessable": True,
                        "key_terms": [term],
                        "evidence_ordinals": [index],
                    }
                )

        # Chain them, so a fake ingest yields a graph with genuine depth rather
        # than a flat row of orphans.
        prerequisites = [
            {
                "prereq_slug": concepts[i]["slug"],
                "target_slug": concepts[i + 1]["slug"],
                "confidence": round(0.6 + 0.3 * _seeded_unit_interval(concepts[i]["slug"], concepts[i + 1]["slug"]), 3),
                "rationale": "Deterministic fake chaining within a window.",
            }
            for i in range(len(concepts) - 1)
        ]

        return {"concepts": concepts, "prerequisites": prerequisites}

    def _merge(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        listed = re.findall(r"^\s*[-*]?\s*([a-z0-9]+(?:-[a-z0-9]+)*)\b", str(variables.get("concepts", "")), re.M)
        slugs: list[str] = []
        for slug in listed:
            if slug not in slugs:
                slugs.append(slug)

        # No merges: the fake has no semantic judgement and inventing one would
        # make dedup tests assert against nonsense.
        edges = [
            {
                "prereq_slug": slugs[i],
                "target_slug": slugs[i + 1],
                "confidence": round(0.5 + 0.4 * _seeded_unit_interval(slugs[i], slugs[i + 1]), 3),
                "rationale": "Deterministic fake ordering across windows.",
            }
            for i in range(len(slugs) - 1)
        ]
        return {"merges": [], "edges": edges, "roots": slugs[:1]}

    def _prereq_infer(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """A section that USES another skill probably depends on it.

        Crude, but it is a real signal rather than a constant, and it is
        deterministic -- which is what makes the edge-inference stage testable
        with no key. A real model reads for "recall that", "by the simplex
        method", "since the matrix is invertible"; this reads for the title, for
        the title's content words under a morphological fold, and for terms
        distinctive to the skill's summary.

        Note what the forward prompt can and cannot support: each skill arrives
        as a title plus ~110 characters of summary, so "distinctive" here is
        measured across 110-character snippets and the term cues are thin. The
        reverse role gets a skill's whole defining passage and the candidates'
        own prose, which is why it can see dependencies this cannot.
        """
        text = str(variables.get("section_text", ""))
        target = str(variables.get("section_slug", ""))
        entries = _parse_skill_list(str(variables.get("skill_list", "")))
        if not entries:
            return {"edges": []}

        frequency = _document_frequency([f"{title} {summary}" for _, title, summary in entries])
        haystack = _prepare(text)

        edges: list[dict[str, Any]] = []
        for slug, title, summary in entries:
            if slug == target:
                pass  # a section is never its own prerequisite
            else:
                cues = _skill_cues(title, f"{title} {summary}", frequency, len(entries))
                score, evidence = _score_cues(cues, haystack)
                if score < CUE_THRESHOLD or not evidence:
                    pass  # nothing quotable, so nothing to claim
                else:
                    edges.append(
                        {
                            "prereq_slug": slug,
                            "target_slug": target,
                            "confidence": _cue_confidence(score),
                            "evidence": evidence,
                        }
                    )

        edges.sort(key=lambda e: (-e["confidence"], e["prereq_slug"]))
        return {"edges": edges[:12]}

    def _prereq_dependents(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """The mirror question: which of these candidate sections use the source?

        The evidence lives in the candidates' excerpts, which the prompt carries,
        so the fake reads them the same way the real model is asked to -- and
        quotes from the excerpt it is accusing, never from the source's own text.

        This is where the fake gets its leverage: the source's full defining
        passage is present, so its characteristic vocabulary ("invertible",
        "linearly independent") is available as a cue, and document frequency
        across the batch tells that vocabulary apart from the words every section
        in the book uses.
        """
        source_slug = str(variables.get("source_slug", ""))
        source_title = str(variables.get("source_title", ""))
        source_text = str(variables.get("source_text", ""))
        candidates = _parse_candidates(str(variables.get("candidates", "")))
        if not candidates:
            return {"dependents": []}

        frequency = _document_frequency([excerpt for _, _, excerpt in candidates])
        cues = _skill_cues(source_title, f"{source_title} {source_text}", frequency, len(candidates), terms=True)

        dependents: list[dict[str, Any]] = []
        for slug, _title, excerpt in candidates:
            if slug == source_slug:
                pass  # a skill is never its own dependent
            else:
                score, evidence = _score_cues(cues, _prepare(excerpt))
                if score < CUE_THRESHOLD or not evidence:
                    pass  # nothing quotable in this candidate's own prose
                else:
                    dependents.append(
                        {"target_slug": slug, "confidence": _cue_confidence(score), "evidence": evidence}
                    )

        dependents.sort(key=lambda d: (-d["confidence"], d["target_slug"]))
        return {"dependents": dependents[:CUE_MAX_DEPENDENTS]}
    def _section_segment(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Name fragments from their lead-in line only.

        The boundaries arrive already decided -- `app.ingestion.segment` cuts
        them out of the book's own typography -- so the only thing this role
        adds is a name, and the only naming signal a deterministic reader has is
        the lead-in the author wrote. `Definition: Matrix Multiplication` yields
        "Matrix Multiplication"; a bare `Definition` yields "Definition", which
        the caller rejects as a label and replaces with its own structural
        title. Doing it this way means the fake exercises that rejection path on
        every ingest rather than leaving it untested until a real model
        misbehaves.

        Never folds (`standalone` is always true): a word-counting stand-in has
        no basis for deciding two passages are the same concept, and one that
        guessed would make the segmentation tests assert against nonsense.
        """
        fragments: list[dict[str, Any]] = []
        for match in SEGMENT_FRAGMENT.finditer(str(variables.get("fragments", ""))):
            index, lead_in, body = int(match.group(1)), match.group(2).strip(), match.group(3).strip()
            named = SEGMENT_LEAD_IN_NAME.match(lead_in)
            title = ((named.group(1).strip() if named else lead_in) or "Fragment")[:80]
            summary = f"{title} — {body[:200]}".strip() if body else f"{title}, as the section presents it."
            fragments.append(
                {
                    "index": index,
                    "title": title,
                    "summary": summary if len(summary) >= 20 else f"{summary} (as presented in the section)",
                    "standalone": True,
                    "key_terms": _salient_terms(body, limit=3),
                }
            )

        return {"fragments": fragments}

    def _node_summary(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Caption each node from the first sentence of its own excerpt that
        names it.

        Deliberately weaker than `app.ingestion.summarise.section_summary`, which
        is what runs when no provider is configured. A fake that matched the
        deterministic path would make "did asking a model help?" unanswerable,
        and would hide the fallback that every declined node relies on: the two
        nodes below whose excerpts say nothing about their own title are omitted
        here, which is exactly what a real model is told to do with them.
        """
        summaries: list[dict[str, Any]] = []
        for slug, title, excerpt in _parse_candidates(str(variables.get("nodes", ""))):
            words = [w.lower() for w in WORD.findall(title) if w.lower() not in TITLE_FILLER]
            sentence = _first_sentence_naming(excerpt, words)
            if not sentence:
                pass  # nothing in the excerpt is about this node; omit it
            else:
                summaries.append({"slug": slug, "summary": f"{title}: {sentence}"[:400]})

        return {"summaries": summaries}

    def _campaign_outcome_eval(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        outcome = str(variables.get("outcome", ""))
        outcome_words = {_stem(word.lower()) for word in WORD.findall(outcome)} - STOPWORDS
        matched_slugs: list[str] = []
        covered_words: set[str] = set()

        for line in str(variables.get("skills", "")).splitlines():
            parts = [part.strip() for part in line.removeprefix("-").strip().split("|", 2)]
            if len(parts) != 3:
                pass
            else:
                slug, title, summary = parts
                skill_words = {_stem(word.lower()) for word in WORD.findall(f"{title} {summary}")} - STOPWORDS
                overlap = outcome_words & skill_words
                if overlap:
                    matched_slugs.append(slug)
                    covered_words.update(overlap)

        missing = sorted(word for word in outcome_words if word not in covered_words)
        readiness = round(len(covered_words) / len(outcome_words), 4) if outcome_words else 0.0
        if matched_slugs:
            rationale = "The generated skills cover these objective terms: " + ", ".join(sorted(covered_words)) + "."
        else:
            rationale = "The generated skill summaries do not clearly cover the stated objective yet."
        return {
            "matched_skill_slugs": matched_slugs,
            "missing_capabilities": missing,
            "readiness": readiness,
            "rationale": rationale,
        }


    def _curriculum_plan(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """The deterministic floor for goal-first construction.

        Not a mock of the planner: the same assembly the service would use with
        no provider configured. A shipped instrument returns its own published
        curriculum; anything else returns the shared catalogue spine with the
        catalogue's suggested ordering. Either way the caller gets a real,
        ordered, playable tree with no keys and no network.
        """
        from app.curricula.planner import assemble, resolve_instrument

        goal = str(variables.get("goal", ""))
        instrument = str(variables.get("instrument", "")).strip() or resolve_instrument(goal) or "piano"
        definition = assemble(instrument)
        concepts: list[dict[str, Any]] = []
        for concept in definition.concepts:
            entry: dict[str, Any] = {"slug": concept.slug}
            if concept.catalogue_id is not None:
                entry["from"] = concept.catalogue_id
                entry["title"] = concept.title
                entry["summary"] = concept.summary
                entry["difficulty"] = concept.difficulty
                entry["key_terms"] = list(concept.key_terms)[:6]
            else:
                entry["title"] = concept.title
                entry["summary"] = concept.summary
                entry["difficulty"] = concept.difficulty
                entry["key_terms"] = list(concept.key_terms)[:6]
            concepts.append(entry)
        edges = [
            {
                "prereq": edge.prereq,
                "target": edge.target,
                "confidence": round(float(edge.confidence), 3),
                **({"rationale": edge.rationale[:200]} if edge.rationale else {}),
            }
            for edge in definition.edges
        ]
        return {
            "instrument": definition.slug,
            "instrument_title": definition.title,
            "concepts": concepts[:24],
            "edges": edges[:60],
        }

    def _course_qa(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Extractive answer: the retrieved passage with the most question
        vocabulary in it, quoted rather than paraphrased.

        A word-counting stand-in has no business composing an explanation, so it
        does not compose one -- it says which passage answers the question and
        quotes it. That still exercises everything the real path needs: identifier
        round-tripping, the citation filter, and the "no passage covers this"
        branch, which fires here whenever nothing overlaps.
        """
        question = str(variables.get("question", ""))
        passages = _parse_passages(str(variables.get("passages", "")))
        asked = {_stem(w.lower()) for w in WORD.findall(question)} - STOPWORDS

        scored = [
            (len(asked & ({_stem(w.lower()) for w in WORD.findall(text)} - STOPWORDS)), -index, index)
            for index, (_, _, _, _, text) in enumerate(passages)
        ]
        best = max(scored, default=None)

        if best is None or best[0] == 0:
            return {
                "answer": "The retrieved material does not cover that question.",
                "citations": [],
            }

        slug, title, node_id, chunk_id, text = passages[best[2]]
        quote = " ".join(text.split())[:CUE_QUOTE_CHARS]
        return {
            "answer": f"{title} is the part of this course that covers it. The material says: {quote}",
            "citations": [{"node_id": node_id, "chunk_id": chunk_id, "quote": quote}],
        }

    def _question(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        title = str(variables.get("node_title", "this concept"))
        summary = str(variables.get("node_summary", ""))
        # Exclude the node's own title, or the rubric degenerates into the
        # tautology "Explains the role of vectors in Vectors."
        title_words = {_stem(w.lower()) for w in WORD.findall(title)}
        terms = _salient_terms(f"{summary} {variables.get('context', '')}", limit=2, exclude=title_words) or ["the idea"]

        rubric = [
            {"id": f"kp{i + 1}", "point": f"Explains the role of {term} in {title}.", "weight": round(1 / len(terms), 3)}
            for i, term in enumerate(terms)
        ]
        # Weights must sum to 1.0 despite rounding.
        rubric[-1]["weight"] = round(1.0 - sum(point["weight"] for point in rubric[:-1]), 3)

        requested_type = str(variables.get("requested_type", "short_answer"))
        if requested_type == "mcq":
            correct_text = summary[:280] or f"The source-based explanation of {title}."
            options = [
                {"id": "option-a", "text": f"It is unrelated to {title}."},
                {"id": "option-b", "text": correct_text},
                {"id": "option-c", "text": f"It only describes the name of {title}."},
                {"id": "option-d", "text": f"It applies only when {terms[0]} is absent."},
            ]
            return {
                "question_type": "mcq",
                "question": f"Which statement best explains why {title} matters?",
                "options": options,
                "correct_option_id": "option-b",
                "accepted_answers": [],
                "code_language": None,
                "code_requirements": [],
                "rubric": [{"id": "kp1", "point": f"Identifies the source-based explanation of {title}.", "weight": 1.0}],
                "difficulty": 1 + int(_seeded_unit_interval(title) * 4),
            }

        if requested_type == "cloze":
            answer = terms[0]
            return {
                "question_type": "cloze",
                "question": f"Complete the key statement about {title}: the concept depends on _____.",
                "options": [],
                "correct_option_id": None,
                "accepted_answers": [answer],
                "code_language": None,
                "code_requirements": [],
                "rubric": [{"id": "kp1", "point": f"Supplies the key term {answer}.", "weight": 1.0}],
                "difficulty": 1 + int(_seeded_unit_interval(title) * 4),
            }

        if requested_type == "code":
            requirement = terms[0]
            return {
                "question_type": "code",
                "question": f"Write a small Python snippet for {title} that demonstrates {requirement}.",
                "options": [],
                "correct_option_id": None,
                "accepted_answers": [],
                "code_language": "python",
                "code_requirements": ["return", requirement],
                "rubric": [{"id": "kp1", "point": f"Uses code to demonstrate {requirement}.", "weight": 1.0}],
                "difficulty": 1 + int(_seeded_unit_interval(title) * 4),
            }

        return {
            "question_type": "short_answer",
            "question": f"Explain {title} in your own words, and say why it matters.",
            "options": [],
            "correct_option_id": None,
            "accepted_answers": [],
            "code_language": None,
            "code_requirements": [],
            "rubric": rubric,
            "difficulty": 1 + int(_seeded_unit_interval(title) * 4),
        }

    def _performance_feedback(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Echo the deterministic examiner's floor back, schema-valid.

        A word-counting stand-in has nothing to add to coaching prose, so it
        returns the deterministic feedback unchanged: the merge path, the schema
        contract, and the fallback behaviour all run for real in fake mode,
        while the learner-facing wording stays exactly as coherent as the floor
        that produced it.
        """
        block = str(variables.get("deterministic_feedback", ""))
        lines = [line.strip() for line in block.splitlines() if line.strip()]

        def value_after(label: str) -> str:
            for line in lines:
                if line.startswith(label):
                    return line[len(label) :].strip()
            return ""

        def bullets_after(label: str) -> list[str]:
            started = False
            bullets: list[str] = []
            for line in lines:
                if line.startswith(label):
                    started = True
                elif started:
                    if line.startswith("- "):
                        bullets.append(line[2:].strip())
                    elif line.startswith(("Persona:", "Tone:", "Summary:", "Corrections:", "Next step:")):
                        started = False
            return bullets

        tone = value_after("Tone:")
        return {
            "summary": value_after("Summary:") or "A closer look at this take is worthwhile.",
            "tone": tone if tone in ("celebratory", "encouraging", "coaching", "supportive") else "coaching",
            # Empty lists echo the floor's silence: a clean run has no
            # corrections, and fabricating one would be a lie.
            "strengths": bullets_after("Strengths:"),
            "corrections": bullets_after("Corrections:"),
            "next_step": value_after("Next step:") or "Replay the exercise slowly and listen for the details.",
        }

    def _score_compose(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Return the procedural floor's own notes, as a schema-valid payload.

        A word matcher cannot compose music, and inventing a phrase here would
        produce something unplayable that the caller would then discard -- which
        exercises nothing. Echoing the floor instead means fake mode walks the
        real path end to end: schema validation, `notes_from_payload`, the
        renderer, and the parser self-check all run for real, and the score the
        learner gets with no API key is a genuine, playable exercise.
        """
        raw = str(variables.get("procedural_notes", "")).strip()
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            parsed = []

        notes: list[dict[str, Any]] = []
        for entry in parsed if isinstance(parsed, list) else []:
            if isinstance(entry, Mapping):
                note: dict[str, Any] = {"beats": float(entry.get("beats", 1))}
                if entry.get("drum"):
                    note["drum"] = str(entry["drum"])
                elif entry.get("step") is None:
                    note["step"] = None
                else:
                    note["step"] = str(entry["step"])
                    note["alter"] = int(entry.get("alter", 0) or 0)
                    note["octave"] = int(entry.get("octave", 4))
                if entry.get("chord"):
                    note["chord"] = True
                notes.append(note)

        title = str(variables.get("skill_title", "")).strip() or "Practice Exercise"
        if not notes:
            # The floor was unreadable, so there is nothing to echo. An empty
            # list fails schema validation and the caller keeps its own score --
            # which is the correct outcome, reached honestly.
            return {"title": title, "notes": []}
        return {"title": f"{title} Exercise", "rationale": "Echoes the deterministic floor.", "notes": notes}

    def _live_coach_cue(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Echo the deterministic cue the caller already computed."""
        cue = str(variables.get("deterministic_cue", "")).strip()
        return {"utterance": cue or "Keep going -- I'm listening."}

    # @spec LLM-FAKE-005
    async def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream the deterministic cue one word at a time.

        Genuinely useful rather than a stub: it runs the real `prepare()`, so the
        prompt hash, version, and fingerprint that reach the ledger are the real
        ones, and it emits word by word with a configurable delay so the client's
        incremental render, the barge-in cancel path, and the terminal ledger
        write are all exercised with no keys and no network.
        """
        del course_id
        call = prepare(role, variables, self.model)
        text = str(variables.get("deterministic_cue", "")).strip() or "Keep going -- I'm listening."
        delay = get_settings().fake_stream_delay_seconds
        words = text.split(" ")
        for index, word in enumerate(words):
            if delay > 0:
                await asyncio.sleep(delay)
            yield StreamDelta(text=word if index == 0 else f" {word}")
        del call

    def _grade(self, variables: Mapping[str, Any]) -> dict[str, Any]:
        answer = str(variables.get("answer", ""))
        rubric_text = str(variables.get("rubric", ""))

        answer_words = {_stem(w.lower()) for w in WORD.findall(answer)} - STOPWORDS

        # Score by how much of each rubric point the answer's vocabulary covers.
        # Crude, but monotonic in answer quality, which is what makes the drill
        # and EXP loop testable. Only the point's *substance* counts -- see
        # RUBRIC_SCAFFOLD.
        hit: list[str] = []
        missed: list[tuple[str, str]] = []
        parsed = (RUBRIC_LINE.match(line) for line in rubric_text.splitlines() if line.strip())
        for match in (m for m in parsed if m is not None):
            point_id, point_text = match.group(1).lower(), match.group(2).strip()
            expected = {_stem(w.lower()) for w in WORD.findall(point_text)} - STOPWORDS - RUBRIC_SCAFFOLD
            overlap = len(expected & answer_words) / max(len(expected), 1)
            if overlap >= 0.34:
                hit.append(point_id)
            else:
                missed.append((point_id, point_text))

        if not hit and not missed:
            missed = [("kp1", "the main idea")]

        score = round(len(hit) / max(len(hit) + len(missed), 1), 3)
        verdict = "correct" if score >= 0.85 else ("incorrect" if score < 0.35 else "partial")

        # Name the points in prose. Printing the ids at the learner leaks an
        # internal identifier into the one piece of copy that has to feel human.
        missing_prose = "; ".join(text.rstrip(".") for _, text in missed)
        if score >= 0.85:
            feedback = "You covered the key ideas. Good, specific answer."
        elif score < 0.35:
            feedback = f"Your answer did not get to the main idea. Still needed: {missing_prose}. Re-read the source."
        else:
            feedback = f"You got part of this. Still missing: {missing_prose}."

        return {
            "score": score,
            "verdict": verdict,
            "feedback": feedback,
            "points_hit": hit,
            "points_missed": [point_id for point_id, _ in missed],
        }


# @spec LLM-EMBED-002, LLM-EMBED-004
class FakeEmbeddingProvider:
    """Deterministic hash-seeded unit vectors.

    Enough to exercise storage, batching, and the retrieval round trip. Useless
    for actual relevance -- two texts sharing no words land in unrelated
    directions, which is exactly what you want a fake to make obvious.
    """

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        # Bag-of-words hashing, so texts sharing vocabulary do end up closer --
        # which makes the fake at least directionally sane for merge tests.
        vector = [0.0] * self.dimensions
        words = [w.lower() for w in WORD.findall(text)] or ["empty"]
        for word in words:
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
