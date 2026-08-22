"""Turning a document's table of contents into nodes and section labels.

The regression behind this module: LLM-inferred extraction on a real 89-page
optimisation textbook produced nodes called "Consider", "Slacky", "Endpoint",
"Accessed" and "1 0", chained 17 deep. The same book's outline gives "Matrix
product", "Simplex Algorithm Procedure" and "The KKT Theorem" in a tree six
deep. These tests pin the properties that make that difference real.
"""

from __future__ import annotations

from app.ingestion import toc
from app.ingestion.parsers.base import TocEntry
from app.ingestion.toc import (
    build_introduces_edges,
    build_toc_nodes,
    difficulty_from_depth,
    is_drillable,
    is_front_or_back_matter,
    is_generic_section,
    section_labels,
    slugify,
)

# A faithful miniature of the CO 250 outline, including its front and back matter.
BOOK = [
    TocEntry(1, "Preface", 3),
    TocEntry(1, "Prerequisite knowledge", 4),
    TocEntry(2, "Matrix product", 4),
    TocEntry(2, "Inverse of a Matrix", 5),
    TocEntry(1, "Formulations", 9),
    TocEntry(2, "Overview", 9),
    TocEntry(2, "LP models", 10),
    TocEntry(3, "The formulation of LP", 11),
    TocEntry(2, "IP models", 13),
    TocEntry(1, "Duality", 53),
    TocEntry(2, "Weak Duality", 53),
    TocEntry(2, "Strong Duality", 56),
    TocEntry(1, "References", 88),
]


def nodes_of(entries: list[TocEntry], page_count: int = 89):
    return build_toc_nodes(entries, page_count)


def by_slug(nodes):
    return {node.slug: node for node in nodes}


# ── what gets in ──────────────────────────────────────────────────────────


def test_front_and_back_matter_are_dropped() -> None:
    """A bibliography is where the node called "Accessed" came from."""
    slugs = {node.slug for node in nodes_of(BOOK)}
    assert "preface" not in slugs
    assert "references" not in slugs
    assert "matrix-product" in slugs


def test_front_matter_detection_is_by_exact_title() -> None:
    assert is_front_or_back_matter("References")
    assert is_front_or_back_matter("  Acknowledgements  ")
    # A real chapter that merely mentions one of those words must survive.
    assert not is_front_or_back_matter("Index Notation for Tensors")


def test_leading_numbers_are_stripped_from_title_and_slug() -> None:
    nodes = nodes_of([TocEntry(1, "3.2.1 Cutting Planes", 4), TocEntry(1, "Chapter 4 Duality", 9)])
    titles = [node.title for node in nodes]
    assert titles == ["Cutting Planes", "Duality"]
    # A renumbered second edition must merge against the first, not duplicate it.
    assert [node.slug for node in nodes] == ["cutting-planes", "duality"]


def test_repeated_section_titles_stay_distinct() -> None:
    """"Overview" appears once per chapter in many books."""
    nodes = nodes_of(
        [
            TocEntry(1, "Formulations", 4),
            TocEntry(2, "Overview", 4),
            TocEntry(1, "Duality", 20),
            TocEntry(2, "Overview", 20),
        ]
    )
    slugs = [node.slug for node in nodes]
    assert len(set(slugs)) == len(slugs), slugs


# ── shape ─────────────────────────────────────────────────────────────────


def test_a_section_labels_every_skill_beneath_it() -> None:
    """The outline survives as provenance, at the outermost heading."""
    labels = section_labels(nodes_of(BOOK))

    assert labels["matrix-product"] == "Prerequisite knowledge"
    assert labels["the-formulation-of-lp"] == "Formulations"
    assert labels["strong-duality"] == "Duality"


def test_a_chapter_labels_itself() -> None:
    """A top-level entry is its own section, not an orphan."""
    labels = section_labels(nodes_of(BOOK))
    assert labels["duality"] == "Duality"


def test_the_outline_contributes_no_edges_at_all() -> None:
    """Containment is not a prerequisite relation.

    This is the whole change. `build_toc_spine` emitted one parent -> child edge
    per entry at 0.95, which on CO 250 was 38 of 77 edges -- half the graph was
    the table of contents, asserted above every edge derived from the prose. A
    chapter is where a concept was printed, not what it requires.
    """
    assert "build_toc_spine" not in dir(toc)


def test_an_outline_that_starts_at_level_two_still_has_chapters() -> None:
    """Some producers emit every entry at level 2+. Depth is relative."""
    nodes = nodes_of([TocEntry(2, "Alpha", 1), TocEntry(3, "Alpha One", 2), TocEntry(2, "Beta", 5)])
    assert [node.level for node in nodes] == [1, 2, 1]
    assert by_slug(nodes)["alpha-one"].parent_slug == "alpha"


# ── page ranges ───────────────────────────────────────────────────────────


def test_a_page_range_ends_where_the_next_entry_begins() -> None:
    nodes = by_slug(nodes_of(BOOK))
    assert nodes["matrix-product"].page_start == 4
    assert nodes["matrix-product"].page_end == 5


def test_dropped_back_matter_still_bounds_the_last_real_section() -> None:
    """"References" is not a node, but it is still a boundary.

    Without this the final chapter absorbs the bibliography's pages and its
    drills quote citations as if they were course material.
    """
    nodes = by_slug(nodes_of(BOOK, page_count=100))
    assert nodes["strong-duality"].page_end == 88  # where References begins


def test_the_final_entry_runs_to_the_end_when_nothing_follows() -> None:
    nodes = by_slug(nodes_of([TocEntry(1, "Alpha", 2), TocEntry(1, "Beta", 6)], page_count=40))
    assert nodes["beta"].page_end == 40


def test_every_range_is_non_empty() -> None:
    """Two entries on one page must not produce a zero-width range, or the
    section owns no chunks and its drills have no source material."""
    nodes = nodes_of([TocEntry(1, "Alpha", 4), TocEntry(1, "Beta", 4), TocEntry(1, "Gamma", 9)])
    assert all(node.page_end > node.page_start for node in nodes)


# ── misc ──────────────────────────────────────────────────────────────────


def test_difficulty_rises_with_dependency_depth_and_stays_in_range() -> None:
    assert difficulty_from_depth(0, 5) < difficulty_from_depth(3, 5) < difficulty_from_depth(5, 5)
    assert all(1 <= difficulty_from_depth(d, 5) <= 5 for d in range(6))


def test_difficulty_does_not_stretch_a_shallow_graph_across_the_whole_scale() -> None:
    """Three layers must not mean "Intro, Moderate, Advanced" and nothing else."""
    assert [difficulty_from_depth(d, 2) for d in range(3)] == [1, 2, 3]


def test_difficulty_saturates_rather_than_overflowing_on_a_deep_graph() -> None:
    """CS 246's outline reaches depth 10; the EXP table only understands 1-5."""
    values = [difficulty_from_depth(d, 10) for d in range(11)]
    assert values[0] == 1
    assert values[-1] == 5
    assert values == sorted(values)


def test_difficulty_no_longer_comes_from_outline_nesting() -> None:
    """The inversion this replaced.

    CO 250 put convex hulls (chapter 4) at graph depth 5 and the KKT theorem
    (the last section of the book) at depth 2 -- but by OUTLINE level they are
    both level-2 sections, so nesting depth could not tell them apart at all,
    while it happily rated every chapter easier than its own sections.
    """
    nodes = by_slug(nodes_of(BOOK))
    assert nodes["lp-models"].level == nodes["weak-duality"].level
    # Same nesting, different position in the dependency graph, different answer.
    assert difficulty_from_depth(1, 5) != difficulty_from_depth(4, 5)


# ── which headings are skills, and which are only structure ───────────────


def test_a_heading_that_owns_no_chunk_is_not_drillable() -> None:
    """A chapter whose first section starts on its own opening page."""
    container = by_slug(nodes_of(BOOK))["formulations"]
    assert container.has_children is True
    assert is_drillable(container, owned_chunks=0) is False


def test_a_chapter_with_an_opener_of_its_own_stays_drillable() -> None:
    """CO 250's "Integer programs" spends a page on IP-vs-LP hardness first.

    "Has children" would blank it. Chunk ownership keeps it.
    """
    chapter = by_slug(nodes_of(BOOK))["formulations"]
    assert chapter.has_children is True
    assert is_drillable(chapter, owned_chunks=3) is True


def test_a_leaf_with_no_text_at_all_is_not_drillable_either() -> None:
    """The second population: a bookmark pointing at a page of figures.

    Six real books: CS 251 has seven of these, MATH 239 three. They are not
    containers -- they have no children -- and they were shipped drillable with
    nothing for question generation to retrieve against.
    """
    leaf = by_slug(nodes_of(BOOK))["inverse-of-a-matrix"]
    assert leaf.has_children is False
    assert is_drillable(leaf, owned_chunks=0) is False
    assert is_drillable(leaf, owned_chunks=1) is True


def test_a_container_heading_is_flagged_as_having_children() -> None:
    nodes = by_slug(nodes_of(BOOK))
    assert nodes["lp-models"].has_children is True
    assert nodes["inverse-of-a-matrix"].has_children is False


def test_slugify_is_stable_and_bounded() -> None:
    assert slugify("Two-phase Simplex (Certificate of Infeasibility)") == "two-phase-simplex-certificate-of-infeasibility"
    assert len(slugify("x" * 200)) <= 64


def test_too_few_entries_yields_nothing_so_the_llm_path_runs() -> None:
    """A three-bookmark PDF is not an outline worth trusting."""
    assert build_toc_nodes([], 10) == []


# ── front matter, as it actually appears in real outlines ─────────────────
#
# Exact-slug matching was too brittle. On a converted C++ ebook the entire
# 2967-page outline reduced to "Title Page", "Copyright Page" and "Dedication
# Page"; on Head First Design Patterns the tree opened with "Authors of Head
# First Design Patterns" and "Table of Contents (summary)".


def test_front_matter_survives_a_page_suffix() -> None:
    for title in ("Title Page", "Copyright Page", "Dedication Page"):
        assert is_front_or_back_matter(title), title


def test_front_matter_survives_a_trailing_parenthetical() -> None:
    assert is_front_or_back_matter("Table of Contents (summary)")
    assert is_front_or_back_matter("Contents (detailed)")


def test_book_apparatus_is_dropped_by_prefix() -> None:
    for title in (
        "Authors of Head First Design Patterns",
        "Creators of the Head First Series",
        "About the Author",
        "About this Book",
        "Praise for Head First Design Patterns",
        "How to Use This Book",
        "List of Figures",
    ):
        assert is_front_or_back_matter(title), title


def test_real_chapters_that_merely_contain_a_matter_word_survive() -> None:
    """The prefix list must not eat legitimate content."""
    for title in (
        "Index Notation for Tensors",
        "Reference Frames",
        "Appendix Operators in Practice",
        "The KKT Theorem",
        "Cutting Planes",
        "Copyrighting Software",  # "copyright" is a prefix; this is not front matter
    ):
        assert not is_front_or_back_matter(title), title


def test_a_boilerplate_only_outline_yields_nothing() -> None:
    """Better to fall through to the LLM path than to build a tree of apparatus."""
    entries = [
        TocEntry(1, "Title Page", 0),
        TocEntry(1, "Copyright Page", 1),
        TocEntry(1, "Dedication Page", 2),
        TocEntry(1, "Table of Contents", 3),
    ]
    assert build_toc_nodes(entries, 10) == []


# ── generic section names ─────────────────────────────────────────────────


def test_a_generic_section_is_qualified_by_its_parent() -> None:
    """"Overview" is not a skill. "Formulations: Overview" is."""
    nodes = by_slug(
        nodes_of([TocEntry(1, "Formulations", 4), TocEntry(2, "Overview", 4), TocEntry(2, "LP models", 6)])
    )
    assert nodes["overview"].title == "Formulations: Overview"
    # A specific title is left exactly as the author wrote it.
    assert nodes["lp-models"].title == "LP models"


def test_a_top_level_generic_title_is_left_alone() -> None:
    """With no parent there is nothing to qualify it with."""
    nodes = by_slug(nodes_of([TocEntry(1, "Introduction", 2), TocEntry(1, "Methods", 5), TocEntry(1, "Results", 8)]))
    assert nodes["introduction"].title == "Introduction"


def test_generic_detection_ignores_numbering_and_case() -> None:
    assert is_generic_section("1.1 Overview")
    assert is_generic_section("OVERVIEW")
    assert not is_generic_section("Overview of Convex Duality")


# ── introduces edges ──────────────────────────────────────────────────────


def test_a_container_introduces_nothing() -> None:
    """A heading that owns no prose is filing, and filing is not a prerequisite.

    This is the case that used to supply half of CO 250's edges. "Duality" owns
    no page exclusively because its first subsection starts on its own opening
    page, so it teaches nothing and cannot precede "Weak duality".
    """
    nodes = nodes_of(BOOK)
    # Only leaves own prose -- every heading with children is pure structure.
    parents = {n.parent_slug for n in nodes if n.parent_slug is not None}
    drillable = {n.slug for n in nodes if n.slug not in parents}
    edges = {(e.prereq, e.target) for e in build_introduces_edges(nodes, drillable)}

    assert edges == set(), edges


def test_a_chapter_with_prose_of_its_own_does_introduce_its_sections() -> None:
    """CO 250's "Integer programs" case: children AND a genuine skill.

    It spends page 75 on why an IP is harder than an LP before its first
    subsection begins, so it owns that page and genuinely precedes what follows.
    """
    nodes = nodes_of(BOOK)
    drillable = {n.slug for n in nodes} - {"formulations", "duality"}
    edges = {(e.prereq, e.target) for e in build_introduces_edges(nodes, drillable)}

    assert ("prerequisite-knowledge", "matrix-product") in edges
    # ...but the two headings left as pure structure still introduce nothing.
    assert not any(prereq in {"formulations", "duality"} for prereq, _ in edges)


def test_an_introduces_edge_loses_to_the_prose() -> None:
    """Structural confidence sits BELOW the content passes' floor, deliberately.

    The old spine used 0.95, which outranked every edge actually read out of the
    book. When a claim about where text was printed disagrees with a claim about
    what the text says, the text wins.
    """
    from app.ingestion.prereqs import MIN_CONFIDENCE

    nodes = nodes_of(BOOK)
    edges = build_introduces_edges(nodes, {n.slug for n in nodes})

    assert edges, "fixture must produce at least one edge to make this meaningful"
    assert all(edge.confidence < MIN_CONFIDENCE for edge in edges)
