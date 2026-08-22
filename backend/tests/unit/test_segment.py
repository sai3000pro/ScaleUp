"""Sub-section segmentation: the book's own lead-ins, found structurally.

Every test here runs with no PDF, no database and no LLM. That is the point of
keeping boundary detection pure -- the rule "an `Example` is not a skill" is
worth nothing if checking it needs Docker.
"""

from __future__ import annotations

import pytest

from app.ingestion.segment import (
    TEXTBOOK_MARKERS,
    FirstMention,
    Fragment,
    LeadInMarkers,
    RawFragment,
    SectionInput,
    fallback_title,
    find_lead_in,
    normalise_title,
    section_line_spans,
    segment_sections,
    split_section,
    structural_title,
    title_candidates,
)
from app.llm.base import LLMRole
from app.llm.fake_provider import FakeLLMClient

# Page 84 of CO 250, verbatim from the parser's page text: two definitions, each
# followed by the example that illustrates it.
KKT_PAGE = """Example
Prove the x = (1, 1) is an optimal solution to:
min -x1 -x2
We can find a relaxation LP (We will show why this is the relaxation later)
x is an optimal solution for the relaxation, therefore, x is also an optimal
solution for the original NLP.
Definition
Let f : Rn -> R be a convex function and x in Rn, then, s in Rn is a subgradient
of f at x if
h(x) := f(x) + s(x - x) <= f(x), for all x in Rn
Example
In our previous example, we have f(x) = -x1 + x2 and x = (1, 1), we claim that
(-1, 2) is a subgradient of f at x, and check h(x) <= f(x) holds everywhere.
Definition
Let C in Rn be a convex set and let x in C. The halfspace F = {x : sx <= b} is
supporting C at x if:
- C ⊆ F and
- sx = b. That is, x is on the boundary of F."""

# Page 8: one definition, 328 characters. This section must NOT split.
MATRIX_INEQUALITY_PAGE = """Matrix inequality
Definition: Matrix inequality
Let A and B be two matrices of the same size. We say A <= B if every entry of A
is at most the corresponding entry of B.
If we say:
A <= 0 then every entry of A is at most zero."""


def lines(page_text: str, page: int = 0) -> list[tuple[int, str]]:
    return [(page, line.strip()) for line in page_text.split("\n") if line.strip()]


# ── lead-in detection ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line,kind",
    [
        ("Definition", "definition"),
        ("Definition:", "definition"),
        ("Definition: Matrix Multiplication", "definition"),
        ("Theorem: Farka's Lemma", "theorem"),
        ("Remark", "remark"),
        ("Remark 1", "remark"),
        ("Remarks:", "remark"),
        ("Example", "illustration"),
        ("Examples", "illustration"),
        ("Proof", "illustration"),
        # Named results, which carry no keyword at all.
        ("KKT Theorem", "named"),
        ("KKT Theorem - Subgradient", "named"),
        ("Weak Duality", "named"),
        ("Perfect Matching Theorem", "named"),
        ("Complementary Slackness Theorem - Special Case", "named"),
        ("Simplex Algorithm Procedure", "named"),
    ],
)
def test_recognises_the_lead_ins_this_book_uses(line: str, kind: str) -> None:
    found = find_lead_in(line)
    assert found is not None, line
    assert found[0] == kind


@pytest.mark.parametrize(
    "line",
    [
        # All of these are real standalone lines in CO 250. A "short capitalised
        # line" rule swallows every one and shreds the book into nodes called
        # "True" and "Machine 1" -- the exact failure TOC-first extraction fixed.
        "True",
        "False",
        "Start",
        "Machine 1",
        "Profit from sales",
        "Consider the LP:",
        "We have:",
        "Solution: We have:",  # a solution IS a lead-in, but an attaching one
        "Recall the conditions of using KKT:",
        "This LP is Optimal",
        "Some properties of basis:",
        "Two possible",
        # The running header. Full caps, and it appears on every page of the
        # section -- a case-insensitive "contains Theorem" rule fires on all of
        # them.
        "5.2. THE KKT THEOREM",
        "Definition of a basis is the set of columns",  # prose, not a lead-in
        "",
    ],
)
def test_does_not_fire_on_prose_or_page_furniture(line: str) -> None:
    found = find_lead_in(line)
    assert found is None or found[0] == "illustration", line


def test_markers_are_an_input_not_a_rule() -> None:
    """A source with no marking convention must segment nothing, not guess."""
    unmarked = LeadInMarkers(concept_keywords=frozenset(), attach_keywords=frozenset())
    assert find_lead_in("Definition", unmarked) is None
    assert find_lead_in("KKT Theorem", unmarked) is None
    assert split_section(lines(KKT_PAGE), markers=unmarked) == []


def test_a_new_convention_is_taught_by_data_alone() -> None:
    slides = LeadInMarkers(
        concept_keywords=frozenset({"concept", "idea"}), attach_keywords=frozenset({"demo"})
    )
    assert find_lead_in("Concept: Loop invariants", slides) == ("concept", "Loop invariants")
    assert find_lead_in("Demo", slides) == ("illustration", "")
    assert find_lead_in("Definition", slides) is None


# ── splitting ─────────────────────────────────────────────────────────────


def test_splits_a_section_at_the_boundaries_the_book_drew() -> None:
    fragments = split_section(lines(KKT_PAGE))
    assert [f.kind for f in fragments] == ["definition", "definition"]
    assert [structural_title(f, "The KKT Theorem") for f in fragments] == ["Subgradient", "Halfspace"]


def test_an_example_is_folded_into_the_concept_it_illustrates() -> None:
    """An `Example` introduces no definiendum; it demonstrates the one above.

    Folding keeps the worked example available for retrieval on the concept's
    own drills, which is the most useful passage a question can quote.
    """
    fragments = split_section(lines(KKT_PAGE))
    assert all(f.kind != "illustration" for f in fragments)
    assert "we claim that" in fragments[0].text, "the example was dropped instead of folded"


def test_an_example_before_any_definition_stays_with_the_section_opening() -> None:
    """It illustrates the section's own introduction, so it is not a node."""
    fragments = split_section(lines(KKT_PAGE))
    assert "Prove the x = (1, 1)" not in fragments[0].text


def test_a_section_holding_one_definition_is_left_alone() -> None:
    """`matrix-inequality` is 328 characters and exactly one concept."""
    assert split_section(lines(MATRIX_INEQUALITY_PAGE)) == []


def test_a_stub_fragment_merges_upward_rather_than_becoming_a_node() -> None:
    text = KKT_PAGE + "\nRemark\nThis follows."
    fragments = split_section(text.split("\n") and lines(text))
    assert len(fragments) == 2
    assert "This follows." in fragments[-1].text


def test_a_section_too_short_to_hold_two_concepts_never_splits() -> None:
    short = "Definition\nA is B.\nDefinition\nC is D."
    assert split_section(lines(short)) == []


def test_ordinals_are_dense_after_folding_and_merging() -> None:
    fragments = split_section(lines(KKT_PAGE))
    assert [f.ordinal for f in fragments] == list(range(len(fragments)))


def test_page_ranges_follow_the_lines_they_came_from() -> None:
    first, second = lines(KKT_PAGE, page=4)[:9], lines(KKT_PAGE, page=5)[9:]
    fragments = split_section(first + second)
    assert fragments[0].page_start == 4
    assert fragments[-1].page_end == 6


# ── section spans ─────────────────────────────────────────────────────────


def section(slug: str, title: str, level: int, start: int, end: int) -> SectionInput:
    return SectionInput(slug=slug, title=title, level=level, page_start=start, page_end=end, difficulty=3)


def test_a_section_starts_at_its_heading_not_at_the_page_break() -> None:
    """Page 83 of CO 250 carries the end of 5.1 and then the heading of 5.2.

    Page-granular ownership hands the whole page to 5.2 and buries 5.1's last
    concept -- the epigraph -- inside it.
    """
    pages = [
        "5.1. CONVEXITY\nDefinition\nThe epigraph of f is the set above its graph.\n"
        "5.2\nThe KKT Theorem\nHow can we prove a solution is optimal?\n82"
    ]
    spans = section_line_spans([section("convexity", "Convexity", 2, 0, 1), section("kkt", "The KKT Theorem", 2, 0, 1)], pages)
    assert "The epigraph of f is the set above its graph." in [line for _, line in spans["convexity"]]
    assert "The epigraph of f is the set above its graph." not in [line for _, line in spans["kkt"]]


def test_a_sections_own_heading_is_not_treated_as_a_lead_in() -> None:
    """"The KKT Theorem" is a named result, and left in it opens a fragment
    that duplicates the parent node it hangs off."""
    pages = ["5.2\nThe KKT Theorem\nHow can we prove a solution is optimal?"]
    spans = section_line_spans([section("kkt", "The KKT Theorem", 2, 0, 1)], pages)
    assert "The KKT Theorem" not in [line for _, line in spans["kkt"]]


def test_page_furniture_is_dropped() -> None:
    pages = [f"5.2. THE KKT THEOREM\nDefinition\nA thing is a widget.\n{80 + n}" for n in range(4)]
    spans = section_line_spans([section("kkt", "The KKT Theorem", 2, 0, 4)], pages)
    kept = [line for _, line in spans["kkt"]]
    assert "5.2. THE KKT THEOREM" not in kept
    assert "80" not in kept


def test_a_chapter_heading_precedes_the_section_sharing_its_page() -> None:
    pages = ["Chapter 5\nNonlinear Programs\nWe now turn to nonlinear objectives.\n5.1\nConvexity\nDefinition"]
    spans = section_line_spans(
        [section("nlp", "Nonlinear Programs", 1, 0, 1), section("convexity", "Convexity", 2, 0, 1)], pages
    )
    assert "We now turn to nonlinear objectives." in [line for _, line in spans["nlp"]]
    assert "Definition" in [line for _, line in spans["convexity"]]


# ── naming ────────────────────────────────────────────────────────────────


def raw(lead_in: str, body: str, kind: str = "definition", ordinal: int = 0) -> RawFragment:
    return RawFragment(
        ordinal=ordinal,
        lead_in=lead_in,
        kind=kind,
        lines=tuple([lead_in] + body.split("\n")) if lead_in else tuple(body.split("\n")),
        page_start=0,
        page_end=1,
    )


@pytest.mark.parametrize(
    "lead_in,body,kind,expected",
    [
        ("Definition: Matrix Multiplication", "Let A be...", "definition", "Matrix Multiplication"),
        ("Definition: cut", "Let G be a graph.", "definition", "Cut"),
        ("KKT Theorem - Subgradient", "Let I denote...", "named", "KKT Theorem - Subgradient"),
        ("Definition", "x in S is a local optimum if there exists d > 0", "definition", "Local optimum"),
        ("Definition", "A graph G = (V, E) is bipartite if V splits.", "definition", "Bipartite graph"),
        # Line-broken by the typesetter. A pattern spelled with literal spaces
        # misses this and matches something incidental further down.
        ("Remark", "Then F is a\nsupporting halfspace of C at x.", "remark", "Supporting halfspace"),
    ],
)
def test_structural_titles_come_from_the_books_own_words(
    lead_in: str, body: str, kind: str, expected: str
) -> None:
    assert structural_title(raw(lead_in, body, kind), "Section") == expected


def test_a_generic_word_is_rejected_rather_than_used_as_a_title() -> None:
    """"Set" collides with every other section and teaches a learner nothing."""
    title = structural_title(raw("Definition", "This is a set of things."), "Polyhedra")
    assert title == "Polyhedra (Definition 1)"


def test_a_lead_in_word_lifted_out_of_the_prose_is_rejected() -> None:
    """Seen on STAT 231: "Remarks:" over "recall the definition of" produced a
    node titled "Definition"."""
    title = structural_title(raw("Remarks:", "Recall the definition of independence.", "remark"), "Events")
    assert title == "Events (Remarks 1)"


def test_a_fragment_with_nothing_quotable_is_qualified_by_its_section() -> None:
    title = structural_title(raw("Remark", "See above.", "remark", ordinal=3), "Cutting Planes")
    assert title == "Cutting Planes (Remark 4)"


# ── the whole pass ────────────────────────────────────────────────────────


def full_section(chunks: tuple = ()) -> list[SectionInput]:
    return [
        SectionInput(
            slug="the-kkt-theorem",
            title="The KKT Theorem",
            level=2,
            page_start=0,
            page_end=1,
            difficulty=4,
            chunks=chunks,
        )
    ]


def test_segment_sections_runs_with_no_llm_at_all() -> None:
    outcome = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE])
    assert outcome.sections_split == 1
    assert [f.title for f in outcome.all_fragments()] == ["Subgradient", "Halfspace"]
    assert outcome.sections_named == 0


def test_the_fake_provider_names_fragments_deterministically() -> None:
    outcome = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=FakeLLMClient(), book_title="CO 250"
    )
    again = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=FakeLLMClient(), book_title="CO 250"
    )
    assert outcome.sections_named == 1
    assert [f.title for f in outcome.all_fragments()] == [f.title for f in again.all_fragments()]


def test_a_model_title_that_is_only_a_label_is_replaced_by_the_structural_one() -> None:
    """The fake returns the bare lead-in for an unnamed `Definition`, which is
    exactly the shape a real model gets wrong -- so this path is exercised on
    every fake ingest instead of waiting for a live failure."""
    outcome = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=FakeLLMClient(), book_title="CO 250"
    )
    assert all(f.title not in {"Definition", "Remark", "Example"} for f in outcome.all_fragments())


def test_fragment_slugs_are_unique_and_fit_the_schema() -> None:
    claimed = {"subgradient"}
    outcome = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE], claimed_slugs=claimed)
    slugs = [f.slug for f in outcome.all_fragments()]
    assert "subgradient" not in slugs, "an already-claimed slug was reused"
    assert len(set(slugs)) == len(slugs)
    assert all(len(slug) <= 64 for slug in slugs)


def test_fragment_slugs_do_not_depend_on_the_models_wording() -> None:
    """Slugs are a learner's EXP and review history. Deriving them from the
    model's title would move every node the day the naming model changes."""
    without = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE])
    with_model = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=FakeLLMClient(), book_title="CO 250"
    )
    assert [f.slug for f in without.all_fragments()] == [f.slug for f in with_model.all_fragments()]


def test_fragments_carry_provenance_back_to_chunks() -> None:
    class Chunk:
        def __init__(self, ident: int, start: int, end: int) -> None:
            self.id, self.page_start, self.page_end = ident, start, end

    chunks = (Chunk(1, 0, 0), Chunk(2, 5, 6))
    outcome = segment_sections(full_section(chunks), ["The KKT Theorem\n" + KKT_PAGE])
    for fragment in outcome.all_fragments():
        assert fragment.source_chunk_ids, "a node with no chunks cannot be drilled"
        assert 1 in fragment.source_chunk_ids


def test_a_fragment_inherits_its_sections_difficulty() -> None:
    """Splitting a node must not make its content harder than the book made it."""
    outcome = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE])
    assert all(f.difficulty == 4 for f in outcome.all_fragments())
    assert all(f.level == 3 for f in outcome.all_fragments())


def test_fragments_hang_off_the_section_they_came_from() -> None:
    outcome = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE])
    assert all(f.parent_slug == "the-kkt-theorem" for f in outcome.all_fragments())


def test_the_model_may_fold_a_boundary_but_never_create_one() -> None:
    class Folding(FakeLLMClient):
        async def structured(self, role, variables, *, course_id=None):
            result = await super().structured(role, variables, course_id=course_id)
            if role is LLMRole.SECTION_SEGMENT:
                for item in result.data["fragments"]:
                    item["standalone"] = item["index"] == 0
                # An index nobody offered, and a fragment count nobody asked for.
                result.data["fragments"].append(
                    {"index": 99, "title": "Invented", "summary": "x" * 30, "standalone": True}
                )
            return result

    outcome = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=Folding(), book_title="CO 250"
    )
    assert outcome.all_fragments() == [] or len(outcome.all_fragments()) < 2
    assert outcome.sections_kept_whole == 1


def test_a_naming_failure_costs_polish_and_not_the_split() -> None:
    class Broken(FakeLLMClient):
        async def structured(self, role, variables, *, course_id=None):
            raise RuntimeError("upstream is down") if role is not LLMRole.SECTION_SEGMENT else None

    class Refusing(FakeLLMClient):
        async def structured(self, role, variables, *, course_id=None):
            from app.llm.base import RefusalError

            raise RefusalError("declined")

    outcome = segment_sections(
        full_section(), ["The KKT Theorem\n" + KKT_PAGE], client=Refusing(), book_title="CO 250"
    )
    assert outcome.sections_naming_failed == 1
    assert [f.title for f in outcome.all_fragments()] == ["Subgradient", "Halfspace"]


def test_markers_reach_the_whole_pass() -> None:
    empty = LeadInMarkers(concept_keywords=frozenset(), attach_keywords=frozenset())
    outcome = segment_sections(full_section(), ["The KKT Theorem\n" + KKT_PAGE], markers=empty)
    assert outcome.fragments_total == 0
    assert outcome.sections_kept_whole == 1


def test_every_marker_kind_is_reachable_from_the_default_vocabulary() -> None:
    assert TEXTBOOK_MARKERS.kind_for("Definition") == "definition"
    assert TEXTBOOK_MARKERS.kind_for("Examples") == "illustration"
    assert TEXTBOOK_MARKERS.kind_for("Consider") is None


# ── node identity ─────────────────────────────────────────────────────────
#
# Two nodes with the same title are not a cosmetic problem. A learner cannot
# tell them apart, and every pass that matches skills by name fires once per
# duplicate on every mention in the book: on CO 250 five duplicate-titled
# fragments alone accounted for 143 of 474 inferred prerequisite edges.

# Page 22 of CO 250. All three definitions mention a feasible solution; only the
# second one DEFINES an optimal solution, and it does so as the sentence's
# subject rather than its complement.
OUTCOMES_PAGE = """Possible Outcomes
Definition
All assignment of values to each of the variables is a feasible solution if all the
constraints are satisfied. An optimization problem is feasible if it has at least
one feasible solution, and it is infeasible when no such assignment exists at all.
Definition
- For a maximization problem, an optimal solution is a feasible solution that
maximizes the objective function over the whole of the feasible region.
- For a minimization problem, an optimal solution is a feasible solution that
minimizes the objective function over the whole of the feasible region.
Definition
- A maximization problem is unbounded if for every value M, there exists a
feasible solution whose objective value is greater than M.
- A minimization problem is unbounded if for every value M, there exists a
feasible solution whose objective value is less than M."""


def test_normalise_title_folds_case_and_plural() -> None:
    assert normalise_title("Extreme Points") == normalise_title("extreme point")
    assert normalise_title("Weak  Duality") == "weak duality"


def test_both_sides_of_the_copula_are_candidates() -> None:
    """The definiendum is not reliably the subject or the complement.

    "A directed path in G is a sequence of arcs" defines the subject;
    "s in Rn is a subgradient of f at x" defines the complement. Reading only
    one side titles half the book after its genus.
    """
    path = raw("Definition", "A directed path in G is a sequence of arcs.")
    assert "Directed path in G" in title_candidates(path)
    subgradient = raw("Definition", "Let f be convex, then s in Rn is a subgradient of f at x if")
    assert title_candidates(subgradient)[0] == "Subgradient"


def test_a_definiendum_mid_sentence_is_found() -> None:
    """Spelled `(?:The|A|An)` the subject pattern was case-sensitive and never
    fired on an article inside a sentence, which is where definitions put it."""
    fragment = raw("Definition", "For a maximization problem, an optimal solution is a feasible solution that")
    assert title_candidates(fragment)[0] == "Optimal solution"


def test_the_subject_must_open_a_clause() -> None:
    """Unanchored, the pattern takes the nearest article before the copula
    rather than the sentence's subject: "All assignment of values to each of
    the variables is a feasible solution" came back as "Variables"."""
    fragment = raw("Definition", "All assignment of values to each of the variables is a feasible solution if")
    assert title_candidates(fragment)[0] == "Feasible solution"


def test_a_candidate_longer_than_a_name_is_rejected() -> None:
    fragment = raw("Definition", "A graph G = (V, E) is bipartite if and only if there is a partition of V.")
    assert all(len(c.split()) <= 4 for c in title_candidates(fragment))


def test_a_weak_pattern_may_not_name_a_term_the_book_was_already_using() -> None:
    """A definition INTRODUCES its term. A noun a pattern scraped out of a
    passage the book has been using for forty pages is not that fragment's
    subject -- this is what produced "Answer", "Auxiliary" and "Boundary"."""
    body = "The epigraph of f is the region above its graph."
    late = RawFragment(0, "Definition", "definition", ("Definition", body), 3, 4)
    stale = FirstMention(["the epigraph is mentioned early", "filler", "filler", body])
    fresh = FirstMention(["nothing relevant", "filler", "filler", body])
    assert "Epigraph" not in title_candidates(late, first_mention=stale)
    assert "Epigraph" in title_candidates(late, first_mention=fresh)


def test_a_remark_is_never_named_by_a_weak_pattern() -> None:
    """A `Remark` states a result about things already named, so the fallback
    patterns have no definiendum to find and return the nearest noun instead."""
    # No copula, so only the weak "The X of ..." pattern can find anything here.
    body = "The rank of A tells us how many independent rows the matrix has."
    remark = RawFragment(0, "Remark", "remark", ("Remark", body), 0, 1)
    definition = RawFragment(0, "Definition", "definition", ("Definition", body), 0, 1)
    assert title_candidates(remark) == []
    assert title_candidates(definition) != []


def test_no_two_fragments_in_a_document_share_a_title() -> None:
    outcome = segment_sections(
        [
            section_with("possible-outcomes", "Possible Outcomes", 0, 1),
            section_with("the-kkt-theorem", "The KKT Theorem", 1, 2),
        ],
        [OUTCOMES_PAGE, KKT_PAGE],
    )
    titles = [normalise_title(f.title) for f in outcome.all_fragments()]
    assert len(set(titles)) == len(titles)


def test_a_definition_outranks_a_remark_that_merely_mentions_the_term() -> None:
    """CO 250 says "if x is an optimal solution" on page 19 and only defines
    the term on page 22. First-come naming gave it to the remark."""
    outcome = segment_sections(
        [
            section_with("shortest-paths", "Shortest Paths", 0, 1),
            section_with("possible-outcomes", "Possible Outcomes", 1, 2),
        ],
        [
            "Shortest Paths\nRemark\nIf x is an optimal solution for the above IP and every cost\n"
            "is positive, then the support of x contains the edges of a shortest path between\n"
            "the two endpoints we picked out at the start of the section.\n"
            "Remark\nWe will use this fact repeatedly in the chapters that follow, so it is\n"
            "worth stating it separately here before we go on to the algorithm itself, which\n"
            "reads it off a dual solution rather than searching the graph directly.",
            OUTCOMES_PAGE,
        ],
    )
    owner = {f.title: f.parent_slug for f in outcome.all_fragments()}
    assert owner.get("Optimal solution") == "possible-outcomes"


def test_a_fragment_that_is_the_section_is_not_emitted_beside_it() -> None:
    """A section is already a node. `partial-derivative` holds one definition
    of the partial derivative plus a remark on computing it; emitting the
    definition as a child gives two nodes with one name."""
    outcome = segment_sections(
        [section_with("partial-derivative", "Partial Derivative", 0, 1)],
        [
            "Partial Derivative\nDefinition: Partial Derivative\nJust like ordinary derivatives, the\n"
            "partial derivative is defined as a limit. Let U be an open subset of Rn and f a function\n"
            "from U to R. The partial derivative of f at a point of U is the limit of the usual\n"
            "difference quotient taken in one coordinate, holding every other coordinate fixed while\n"
            "that one varies. It exists exactly when that limit exists.\n"
            "Remark\nTo compute one in practice, treat every other variable as a constant and\n"
            "differentiate as usual. That is what makes the gradient cheap to evaluate coordinate by\n"
            "coordinate, and it is why the KKT conditions are checkable at all for a smooth program."
        ],
    )
    assert outcome.fragments_are_the_section == 1
    assert outcome.sections_kept_whole == 1
    assert outcome.all_fragments() == []


def test_an_explicit_restatement_folds_into_the_node_above_it() -> None:
    body = (
        "Canonical Forms\nDefinition\nLet B be a basis of A. B is an optimal basis if and only if\n"
        "the reduced costs are all non-positive, which is exactly what the simplex test checks at\n"
        "each step before it decides whether to pivot again or to stop and report the answer it\n"
        "has. The test is cheap because the tableau already carries the reduced costs.\n"
        "Remark\nRecall that B is an optimal basis if and only if the reduced costs are all\n"
        "non-positive. We restate it here because the construction on the next page leans on it\n"
        "heavily, and it is easier to have it in front of you than to page backwards for it.\n"
        "It is the same statement, in the same notation, with nothing new added to it."
    )
    outcome = segment_sections([section_with("canonical-forms", "Canonical Forms", 0, 1)], [body])
    assert outcome.fragments_merged_as_restatement == 1
    assert outcome.sections_kept_whole == 1, "one concept left after folding is not a segmentation"


def test_a_restatement_never_merges_past_an_intervening_concept() -> None:
    """Merging backwards over another fragment stretches the target's page
    range across it, and a page-homed reader can no longer see the concept in
    between. CO 250's page 36 "Recall ... optimal basis" swallowed the whole
    simplex-optimality section this way."""
    outcome = segment_sections(
        [section_with("canonical-forms", "Canonical Forms", 0, 3)],
        [
            "Canonical Forms\nDefinition\nLet B be a basis of A. B is an optimal basis if and only\n"
            "if the reduced costs are all non-positive, which is what the simplex test checks.",
            "Definition\nA pivot is a step that exchanges one column of the basis for another one,\n"
            "chosen so that the objective value does not decrease anywhere along the way.",
            "Remark\nRecall that B is an optimal basis if and only if the reduced costs are all\n"
            "non-positive. We restate it here because the next construction leans on it.",
        ],
    )
    assert outcome.fragments_merged_as_restatement == 0
    pages = [(f.page_start, f.page_end) for f in outcome.all_fragments()]
    assert all(end - start <= 2 for start, end in pages), pages


def test_a_qualified_fallback_is_preferred_to_a_plausible_wrong_name() -> None:
    """The fallback is legible as a gap to a learner and to a checker. A
    confidently wrong "Optimal solution" is legible to neither."""
    outcome = segment_sections(
        [section_with("possible-outcomes", "Possible Outcomes", 0, 1)], [OUTCOMES_PAGE]
    )
    titles = [f.title for f in outcome.all_fragments()]
    assert "Optimal solution" in titles
    assert "Feasible solution" in titles
    # The genus is never handed to a second node just because a pattern found it.
    assert titles.count("Feasible solution") == 1


def test_no_title_contains_the_delimiter_prereq_inference_splits_on() -> None:
    """`prereqs.py` renders a skill as ``- `slug` — Title: summary`` and reads
    the title back as everything before the first colon. A colon inside a title
    truncates it to the section name, which then matches every section that
    mentions the section -- 137 spurious edges from one node on CS 246."""
    outcome = segment_sections(
        [section_with("possible-outcomes", "Possible Outcomes", 0, 1)], [OUTCOMES_PAGE]
    )
    assert all(":" not in f.title for f in outcome.all_fragments())
    assert ":" not in fallback_title(raw("Remark", "See above.", "remark"), "Cutting Planes")


def section_with(slug: str, title: str, start: int, end: int) -> SectionInput:
    return SectionInput(slug=slug, title=title, level=2, page_start=start, page_end=end, difficulty=3)


def test_fragment_is_immutable() -> None:
    fragment = Fragment(
        parent_slug="s", slug="f", title="T", summary="S", lead_in="Definition", kind="definition",
        text="t", page_start=0, page_end=1, difficulty=3, level=3,
    )
    with pytest.raises(AttributeError):
        fragment.title = "other"  # type: ignore[misc]
