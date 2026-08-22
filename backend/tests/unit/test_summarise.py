"""Node captions: the defect, and the rules that fix it.

The regression this file exists for is quoted verbatim in KKT_TEXT. On CO 250
`outline_concepts` set `summary = own_text[:280]`, and section 5.2 "The KKT
Theorem" opens with the tail of 5.1 -- so the node the whole chapter builds
towards was captioned with the definition of an *epigraph*. Every assertion below
is either that defect or a rule that was added to stop a specific bad caption
seen on the same book.

Text is copied from the PDF text layer, mangled maths included. A cleaned-up
version of it would not exercise the thing under test.
"""

from __future__ import annotations

from app.ingestion.summarise import (
    is_prose,
    lead_in_of,
    section_summary,
    split_statements,
    strip_math,
)

# Pages 82-85 of CO 250, flattened exactly as `parse_pdf` flattens them.
KKT_TEXT = (
    "Definition Let f : Rn →R be a function. The epigraph of f is given by: epi(f) = y x : y ≥f(x), "
    "x ∈Rn Example Consider f(x) = x2, then the draw of epi(f) is: −3 −2 −1 1 2 3 2 4 6 8 x y Remark "
    "Let f : Rn →R be a function, it follows that: f is convex ⇔epi(f) is convex. How can we prove a "
    "feasible solution ¯x is optimal for an NLP? Definition Let f : Rn →R be a convex function and "
    "¯x ∈Rn, then, s ∈Rn is a subgradient of f at ¯x if h(x) := f(¯x) + s⊤(x −¯x) ≤f(x) for all x ∈Rn. "
    "Example In our previous NLP example, ¯x = (3/4, 3/4)⊤is a slater point. "
    "KKT Theorem Let I denote the set of indices i for which gi(¯x) = 0, consider the following NLP: "
    "min c⊤x s.t. gi(x) ≤0, i = 1, 2, · · · , k Suppose that ¯x is a feasible solution, and −c is in "
    "the cone of tight constraints."
)

MATRIX_TEXT = (
    "Definition: Matrix Multiplication Let A ∈Mm×n(F) and B ∈Mn×p(F). We define the matrix product "
    "AB = C to be the matrix C ∈Mm×p(F), constructed as follows: C = AB = A h b1 b2 · · · bp i = h "
    "A⃗b1 A⃗b2 · · · A⃗bp i . That is, the jth column of C is obtained by multiplying A by the jth "
    "column of B."
)

BASIS_TEXT = (
    "Notation let B be a subset of column indices, then AB is a columns sub-matrix of A indexed by "
    "set B. Ai denotes the columns i of A. Definition Let B be a subset of column indices, B is a "
    "basis if AB is invertible (non-sigular). Remark Some properties of basis: • Max number of "
    "independent columns = Max number of independent rows."
)


# ── the acceptance criterion ──────────────────────────────────────────────


def test_the_kkt_theorem_no_longer_describes_an_epigraph() -> None:
    """The defect, stated as a test. `own_text[:280]` fails this outright."""
    summary = section_summary("The KKT Theorem", KKT_TEXT)

    assert "epigraph" not in summary.lower()
    assert "KKT Theorem" in summary
    assert KKT_TEXT[:280] != summary


def test_a_variant_of_the_title_loses_to_the_title_itself() -> None:
    """"KKT Theorem - Subgradient" is a variant, and it is printed FIRST.

    Earliest-match would caption the node with the subgradient form of the
    theorem rather than the theorem. A dash after the node's own name is what
    tells the two apart.
    """
    text = (
        "KKT Theorem - Subgradient Let I denote the set of indices for which the constraint is "
        "tight, and let s be a subgradient there. "
    ) + KKT_TEXT
    summary = section_summary("The KKT Theorem", text)

    assert "Subgradient" not in summary
    assert summary.startswith("KKT Theorem")


# ── the three rules, in order of strength ─────────────────────────────────


def test_the_sentence_that_names_the_node_beats_the_one_printed_first() -> None:
    summary = section_summary("Matrix product", MATRIX_TEXT)
    assert "matrix product" in summary.lower()


def test_a_definition_lead_in_is_preferred_over_bare_prose() -> None:
    """`Notation let B be ...` is printed first; the `Definition` is the caption."""
    summary = section_summary("Basis", BASIS_TEXT)
    assert summary.startswith("Definition.")
    assert "is a basis if AB is invertible" in summary


def test_a_caption_stops_at_the_next_lead_in() -> None:
    """Running on into `Remark ...` describes the next concept, not this one."""
    assert "Remark" not in section_summary("Basis", BASIS_TEXT)


def test_prose_is_the_last_resort_not_the_first_choice() -> None:
    text = "A dual solution certifies a bound on the primal objective. It is found by inspection."
    assert section_summary("Weak duality", text).startswith("A dual solution certifies")


def test_a_node_with_no_text_gets_no_caption() -> None:
    """`""` is a real answer -- the caller's page-range placeholder is honest,
    and a sentence borrowed from elsewhere is not."""
    assert section_summary("Duality", "") == ""
    assert section_summary("Duality", "  \n  ") == ""


def test_a_node_whose_text_is_pure_mathematics_gets_no_caption() -> None:
    assert section_summary("Simplex", "max c⊤x s.t. Ax = b, x ≥0 A = 1 2 3 1 5 3 b = 2 5") == ""


# ── the token filter ──────────────────────────────────────────────────────


def test_a_flattened_formula_collapses_to_an_ellipsis() -> None:
    collapsed = strip_math("We define AB = C as follows: C = AB = A h b1 b2 · · · bp i = h A⃗b1 i")
    assert "b1 b2" not in collapsed
    assert "…" in collapsed
    # Short inline maths survives: a caption that cannot name its own object is
    # no better than a formula.
    assert "AB = C" in collapsed


def test_a_trailing_conjunction_left_by_the_collapse_is_dropped() -> None:
    """"consider the NLP: min … where" reads as a truncation bug."""
    assert not strip_math("consider the NLP: min c⊤x s.t. gi(x) ≤0, i = 1, 2, k where").endswith("where")


def test_a_word_marooned_between_two_formulae_is_not_a_caption() -> None:
    """`|{z} fixed + t |{z} ∞ →∞ We now have` -- "fixed" is part of a display."""
    tidied = strip_math("c⊤x(t) = c⊤¯x + t c⊤r |{z} 1 = |{z} fixed + t |{z} ∞ →∞ We now have a result")
    assert tidied.startswith("We now have")


def test_mangled_maths_is_not_prose_and_a_definition_is() -> None:
    assert not is_prose("C = AB = A h b1 b2 · · · bp i")
    assert not is_prose("−3 −2 −1 1 2 3 2 4 6 8 x y")
    assert is_prose("Let B be a subset of column indices, B is a basis if AB is invertible.")


def test_a_definition_with_a_display_welded_on_still_reads_as_prose() -> None:
    """35% wordy before the collapse, 76% after. Judged before it, the one
    sentence that says what the node is gets thrown away."""
    assert is_prose(
        "We define the matrix product AB = C to be the matrix C, constructed as follows: "
        "C = AB = A h b1 b2 · · · bp i = h A⃗b1 A⃗b2 · · · A⃗bp i"
    )


# ── sentence splitting ────────────────────────────────────────────────────


def test_an_abbreviation_does_not_end_a_sentence() -> None:
    """`min c⊤x s.t. Ax ≥ b` is one statement. Splitting on `[.!?]\\s+` makes it
    three, two of which are the letters `s` and `t`."""
    statements = split_statements("Consider the LP: min c⊤x s.t. gi(x) ≤0 for all i.")
    assert len(statements) == 1


def test_a_real_sentence_boundary_still_splits() -> None:
    assert len(split_statements("Ai denotes the columns i of A. Definition Let B be a subset.")) == 2


def test_the_maths_ellipsis_is_not_a_bullet() -> None:
    """`x1, x2, · · · , xn` is one indexed family, not four list items."""
    assert len(split_statements("Let a1, a2, · · · , ak be vectors in R")) == 1


def test_a_bullet_list_becomes_separate_statements() -> None:
    statements = split_statements("Some properties: • B is a basis • Not every matrix has one")
    assert len(statements) == 3
    assert not any(part.startswith("•") for part in statements)


def test_a_caption_never_opens_mid_clause() -> None:
    """The bullets split the definition; the sentence naming the concept is the
    third piece, and alone it starts with a bare verb."""
    text = (
        "Definition Suppose a constraint α⊤x ≤β that • is satisfied for all feasible solutions to "
        "the IP, and • is not satisfied for ¯x We then call this constraint a cutting plane for ¯x."
    )
    summary = section_summary("Cutting Planes", text)
    assert summary.startswith("Definition.")
    assert "cutting plane" in summary


# ── lead-in detection, delegated to segment.find_lead_in ──────────────────


def test_the_shortest_lead_in_wins() -> None:
    """`find_lead_in` is anchored to a whole LINE, and a flattened text layer has
    none -- so the longer match has swallowed the statement it announces."""
    assert lead_in_of("Definition: Matrix Multiplication Let A ∈Mm×n(F)") == ("Definition:", "definition")


def test_a_named_result_with_no_keyword_is_still_a_lead_in() -> None:
    assert lead_in_of("Weak Duality Let (P) be a minimization problem") == ("Weak Duality", "named")


def test_ordinary_prose_has_no_lead_in() -> None:
    assert lead_in_of("We wish to find a lower bound to the objective value.") is None


def test_a_label_is_only_punctuated_when_a_sentence_follows_it() -> None:
    """"The Certificate of Optimality is then the scalars vector" is one
    sentence; punctuating it gives ". is then", which reads as a bug."""
    summary = section_summary(
        "Certificate of Optimality",
        "The Certificate of Optimality is then the scalars vector defined by the dual solution y.",
    )
    assert ". is then" not in summary


# ── the shape the rest of the pipeline depends on ─────────────────────────


def test_a_caption_is_one_line_and_bounded() -> None:
    """`prereqs._render_skill_list` puts each skill on ONE line and the fake
    reads it back with a line-anchored regex, so a newline in a summary silently
    deletes that skill from the vocabulary."""
    summary = section_summary("The KKT Theorem", KKT_TEXT)
    assert "\n" not in summary
    assert len(summary) <= 280
