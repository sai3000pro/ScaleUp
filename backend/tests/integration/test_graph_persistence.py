"""The single write path for skill graphs, exercised against a graph this module owns.

The tree below belongs to these tests rather than to the seed. It carries the
two pathologies the write path has to survive -- a transitively implied edge
and a back-edge that would close a cycle -- and it carries them at fixed
confidences, because greedy admission by confidence is exactly what decides
which edge loses. A graph owned elsewhere can have those properties tuned out
from under these assertions by someone improving a curriculum.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.models import Course, SkillEdge, SkillEdgeRejection, SkillNode, User
from app.services.graph_service import persist_graph
from tests.fixtures.skill_graph import CONCEPTS, EDGES


@pytest.fixture
def seeded_course(clean_db: None):
    """Write the fixture graph and hand back the course id."""
    course_id = uuid.uuid4()
    with sync_session() as session:
        user = User(
            email="graph@example.com",
            password_hash=hash_password("hunter22-long-enough"),
            display_name="Graph",
        )
        session.add(user)
        session.flush()
        course = Course(id=course_id, owner_id=user.id, title="Fixture")
        session.add(course)
        session.flush()
        persist_graph(session, course, CONCEPTS, EDGES)
    return course_id


def test_all_concepts_become_nodes(seeded_course: uuid.UUID) -> None:
    with sync_session() as session:
        nodes = session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course)).all()
    assert len(nodes) == len(CONCEPTS)
    assert {node.slug for node in nodes} == {concept.slug for concept in CONCEPTS}


def test_edge_rationale_is_persisted(seeded_course: uuid.UUID) -> None:
    rationale = "The passage states that note names are read before rhythm is."
    candidates = [
        CandidateEdge(
            edge.prereq,
            edge.target,
            edge.confidence,
            edge.support,
            rationale if (edge.prereq, edge.target) == ("note-names", "reading-rhythm") else edge.rationale,
        )
        for edge in EDGES
    ]

    with sync_session() as session:
        course = session.get(Course, seeded_course)
        persist_graph(session, course, CONCEPTS, candidates)

    with sync_session() as session:
        nodes = {
            node.slug: node.id
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course))
        }
        edge = session.get(SkillEdge, (nodes["note-names"], nodes["reading-rhythm"]))

    assert edge is not None
    assert edge.rationale == rationale


def test_the_planted_back_edge_is_rejected_with_its_cycle_path(seeded_course: uuid.UUID) -> None:
    """cadences -> steady-pulse would close a loop; it must not be stored."""
    with sync_session() as session:
        rejections = session.scalars(
            select(SkillEdgeRejection).where(SkillEdgeRejection.course_id == seeded_course)
        ).all()

    assert len(rejections) == 1
    (rejection,) = rejections
    assert (rejection.prereq_slug, rejection.target_slug) == ("cadences", "steady-pulse")
    assert rejection.reason == "cycle"
    # The recorded path is the debugging artifact, not just the label.
    assert rejection.cycle_path[0] == "steady-pulse"
    assert rejection.cycle_path[-1] == "cadences"


def test_transitively_implied_edges_are_stored_but_not_rendered(seeded_course: uuid.UUID) -> None:
    with sync_session() as session:
        slug_by_id = {
            node.id: node.slug
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course))
        }
        edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == seeded_course)).all()

    stored = {(slug_by_id[e.prereq_id], slug_by_id[e.target_id]) for e in edges}
    rendered = {(slug_by_id[e.prereq_id], slug_by_id[e.target_id]) for e in edges if e.is_reduced}

    # Planted shortcut: implied by keyboard-geography -> hand-position -> scales.
    assert ("keyboard-geography", "scales") in stored
    assert ("keyboard-geography", "scales") not in rendered
    # Genuinely implied by triads -> broken-chords -> cadences.
    assert ("triads", "cadences") in stored
    assert ("triads", "cadences") not in rendered

    assert len(rendered) < len(stored)


def test_depths_layer_the_tree(seeded_course: uuid.UUID) -> None:
    with sync_session() as session:
        depth = {
            node.slug: node.depth
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course))
        }

    assert depth["note-names"] == 0  # root
    assert depth["reading-rhythm"] > depth["note-names"]
    assert depth["scale-fingering"] > depth["scales"]
    assert depth["cadences"] > depth["triads"]


def test_rewriting_the_same_graph_is_idempotent(seeded_course: uuid.UUID) -> None:
    with sync_session() as session:
        course = session.get(Course, seeded_course)
        before = course.graph_version
        persist_graph(session, course, CONCEPTS, EDGES)

    with sync_session() as session:
        nodes = session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course)).all()
        edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == seeded_course)).all()
        course = session.get(Course, seeded_course)

    assert len(nodes) == len(CONCEPTS)
    assert len(edges) == len(EDGES) - 1  # everything but the rejected back-edge
    # graph_version still advances -- it counts writes, which is what the
    # Neo4j projection uses to detect staleness.
    assert course.graph_version == before + 1


def test_concepts_dropped_from_a_re_extraction_are_removed(seeded_course: uuid.UUID) -> None:
    trimmed = [c for c in CONCEPTS if c.slug not in {"cadences", "triads"}]
    kept = {c.slug for c in trimmed}
    edges = [e for e in EDGES if e.prereq in kept and e.target in kept]

    with sync_session() as session:
        course = session.get(Course, seeded_course)
        persist_graph(session, course, trimmed, edges)

    with sync_session() as session:
        slugs = {
            node.slug
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == seeded_course))
        }

    assert "cadences" not in slugs
    assert len(slugs) == len(trimmed)


def test_a_cyclic_proposal_never_reaches_the_database(clean_db: None) -> None:
    """The guarantee the whole module exists to provide."""
    from app.domain.dag import topological_depths
    from app.services.graph_service import ConceptSpec

    concepts = [ConceptSpec(slug, slug.title(), "...") for slug in ("a", "b", "c")]
    vicious = [
        CandidateEdge("a", "b", 0.9),
        CandidateEdge("b", "c", 0.8),
        CandidateEdge("c", "a", 0.7),
    ]

    course_id = uuid.uuid4()
    with sync_session() as session:
        user = User(email="cyc@example.com", password_hash=hash_password("hunter22-long"), display_name="C")
        session.add(user)
        session.flush()
        course = Course(id=course_id, owner_id=user.id, title="Cyclic")
        session.add(course)
        session.flush()
        persist_graph(session, course, concepts, vicious)

    with sync_session() as session:
        slug_by_id = {
            n.id: n.slug for n in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))
        }
        stored = [
            CandidateEdge(slug_by_id[e.prereq_id], slug_by_id[e.target_id], e.confidence)
            for e in session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id))
        ]

    # Raises if what we stored is cyclic.
    topological_depths(set(slug_by_id.values()), stored)
