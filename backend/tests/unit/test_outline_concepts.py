"""Turning outline entries into concepts: who gets a skill, who is only structure.

The regression behind this file. On CO 250 a chapter whose first section began
on the chapter's own opening page owned no page exclusively, so it was handed
the first chunks of its own subtree as a stand-in. "Duality" and "Weak duality"
came out with byte-identical text -- same 2696 characters, same pages 54-56 --
and the content-derived prerequisite pass then read the child's prose while
believing it was reading the parent's. Three of the edges it produced came back
out of `build_acyclic_edges` as *duplicates* of the structural edges: the pass
had re-derived the child's own relationships from a copy of the child's text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.ingestion.parsers.base import TocEntry
from app.ingestion.toc import build_toc_nodes, owner_of_page
from app.services.ingest_pipeline import outline_concepts


@dataclass(frozen=True, slots=True)
class FakeChunk:
    """`outline_concepts` reads exactly these three attributes off a Chunk."""

    id: uuid.UUID
    text: str
    page_start: int


def chunk(page: int, text: str) -> FakeChunk:
    return FakeChunk(id=uuid.uuid4(), text=text, page_start=page)


def build(entries: list[TocEntry], chunks: list[FakeChunk], page_count: int = 40):
    nodes = build_toc_nodes(entries, page_count)
    owned_by: dict[str, list[FakeChunk]] = {node.slug: [] for node in nodes}
    for item in chunks:
        owner = owner_of_page(nodes, item.page_start)
        if owner is not None:
            owned_by[owner.slug].append(item)
    concepts = outline_concepts(nodes, owned_by, {n.slug: n.slug for n in nodes})
    return {concept.slug: concept for concept in concepts}


# "Duality" opens on page 10 and its first section starts there too, so it owns
# nothing. "Integer programs" opens on page 20 with a page of its own before its
# first section begins on 21 -- the case a purely structural test gets wrong.
BOOK = [
    TocEntry(1, "Duality", 10),
    TocEntry(2, "Weak duality", 10),
    TocEntry(2, "Strong duality", 13),
    TocEntry(1, "Integer programs", 20),
    TocEntry(2, "Cutting planes", 21),
]
CHUNKS = [
    chunk(10, "A dual solution certifies a bound on the primal objective."),
    chunk(13, "Strong duality closes the gap when both programs are feasible."),
    chunk(20, "An integer program is harder than its linear relaxation."),
    chunk(21, "A cutting plane removes fractional solutions without losing integer ones."),
]


def test_a_container_is_marked_unassessable() -> None:
    concepts = build(BOOK, CHUNKS)
    assert concepts["duality"].assessable is False


def test_a_container_carries_none_of_its_children_text() -> None:
    """The exact bug: parent and child came out byte-identical."""
    concepts = build(BOOK, CHUNKS)

    assert concepts["duality"].source_chunk_ids == ()
    assert concepts["duality"].summary != concepts["weak-duality"].summary
    assert "certifies a bound" not in concepts["duality"].summary


def test_a_container_still_gets_a_readable_placeholder_summary() -> None:
    """It is rendered in the tree, so it cannot be blank."""
    summary = build(BOOK, CHUNKS)["duality"].summary
    assert summary.startswith("Duality")
    assert "pages" in summary


def test_a_chapter_with_its_own_opening_material_stays_a_skill() -> None:
    """`has_children` would have blanked this one."""
    concepts = build(BOOK, CHUNKS)

    assert concepts["integer-programs"].assessable is True
    assert len(concepts["integer-programs"].source_chunk_ids) == 1
    assert "harder than its linear relaxation" in concepts["integer-programs"].summary


def test_a_leaf_with_no_text_is_not_assessable() -> None:
    """The second population, which CO 250 happens not to have.

    Across six books CS 251 has seven of these and MATH 239 three: a bookmark
    whose pages produce no chunk at all. They were emitted drillable with
    nothing for question generation to retrieve against.
    """
    entries = BOOK + [TocEntry(2, "Gomory cuts", 30)]
    concepts = build(entries, CHUNKS)

    assert concepts["gomory-cuts"].source_chunk_ids == ()
    assert concepts["gomory-cuts"].assessable is False


def test_every_node_with_text_is_assessable() -> None:
    concepts = build(BOOK, CHUNKS)
    for concept in concepts.values():
        assert concept.assessable == bool(concept.source_chunk_ids), concept.slug


def test_difficulty_is_left_for_the_graph_to_decide() -> None:
    """It is a function of dependency depth, which is not known until persist."""
    for concept in build(BOOK, CHUNKS).values():
        assert concept.difficulty is None, concept.slug
