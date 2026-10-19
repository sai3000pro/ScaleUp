"""Publication gates, skill transitions between versions, and what a reviewer is shown."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.models import Course, CurriculumVersion, PrerequisiteCandidate, User
from app.schemas.curriculum import CurriculumTransitionIn
from app.services.curriculum_graph_service import (
    MIN_ASSESSMENT_COVERAGE,
    MIN_PUBLISHED_EDGE_CONFIDENCE,
    _project_candidate,
    create_draft,
    publish,
    review_all_candidates,
)
from app.services.graph_service import ConceptSpec


def _concept(slug: str, assessable: bool = True) -> ConceptSpec:
    return ConceptSpec(slug, slug.replace("-", " ").title(), f"About {slug}.", 2, assessable=assessable)


@pytest.fixture
def records() -> dict[str, uuid.UUID]:
    user_id, course_id = uuid.uuid4(), uuid.uuid4()
    with sync_session() as session:
        session.add(User(id=user_id, email=f"gates-{user_id.hex[:8]}@example.com", password_hash="hash", display_name="Gates"))
        session.flush()
        session.add(Course(id=course_id, owner_id=user_id, title="Gated", description=""))
        session.commit()
    return {"user_id": user_id, "course_id": course_id}


def _draft(session, records, concepts, edges, transitions=()) -> uuid.UUID:
    course = session.get(Course, records["course_id"])
    draft = create_draft(session, course, "cello", "Cello", "cello-core", "Cello Core", concepts, edges, transitions=transitions)
    review_all_candidates(session, draft.version_id, records["user_id"])
    return draft.version_id


# @spec CURR-VERSION-007
def test_publication_is_refused_below_the_assessment_coverage_gate(records) -> None:
    concepts = [_concept("a"), _concept("b", assessable=False), _concept("c", assessable=False)]
    assert 1 / 3 < MIN_ASSESSMENT_COVERAGE
    with sync_session() as session:
        version_id = _draft(session, records, concepts, [CandidateEdge("a", "b", 0.9, rationale="r")])
        with pytest.raises(ValueError, match="assessment coverage"):
            publish(session, version_id)


# @spec CURR-VERSION-007
def test_publication_is_refused_when_an_accepted_edge_is_weaker_than_the_gate(records) -> None:
    weak = MIN_PUBLISHED_EDGE_CONFIDENCE - 0.05
    with sync_session() as session:
        version_id = _draft(session, records, [_concept("a"), _concept("b")], [CandidateEdge("a", "b", weak, rationale="r")])
        with pytest.raises(ValueError, match="confidence gate"):
            publish(session, version_id)


# @spec CURR-VERSION-008
def test_a_reviewer_sees_every_unlock_path_an_edge_would_change(records) -> None:
    edges = [
        CandidateEdge("a", "b", 0.9, rationale="r"),
        CandidateEdge("b", "c", 0.9, rationale="r"),
        CandidateEdge("c", "d", 0.9, rationale="r"),
        CandidateEdge("a", "e", 0.9, rationale="r"),
    ]
    with sync_session() as session:
        version_id = _draft(session, records, [_concept(s) for s in "abcde"], edges)
        candidates = {
            (c.prereq_skill_id, c.target_skill_id): c
            for c in session.scalars(
                select(PrerequisiteCandidate).where(PrerequisiteCandidate.curriculum_version_id == version_id)
            )
        }
        by_slug = {_project_candidate(session, c.id).target: _project_candidate(session, c.id) for c in candidates.values()}
        assert by_slug["b"].affected_unlocks == ["b", "c", "d"]
        assert by_slug["d"].affected_unlocks == ["d"]
        assert by_slug["e"].affected_unlocks == ["e"]


# @spec CURR-GRAPH-006
def test_a_skill_cannot_vanish_between_versions_without_a_transition(records) -> None:
    with sync_session() as session:
        first = _draft(
            session, records, [_concept("a"), _concept("b"), _concept("c")], [CandidateEdge("a", "b", 0.9, rationale="r")]
        )
        publish(session, first)
        session.commit()
    with sync_session() as session:
        second = _draft(
            session, records, [_concept("a"), _concept("b-prime")], [CandidateEdge("a", "b-prime", 0.9, rationale="r")]
        )
        with pytest.raises(ValueError, match="no split, merge, rename or retire transition.*b, c"):
            publish(session, second)
    with sync_session() as session:
        transitions = [
            CurriculumTransitionIn(kind="rename", from_skills=["b"], to_skills=["b-prime"], rationale="clearer name"),
            CurriculumTransitionIn(kind="retire", from_skills=["c"], rationale="folded into practice notes"),
        ]
        third = _draft(
            session,
            records,
            [_concept("a"), _concept("b-prime")],
            [CandidateEdge("a", "b-prime", 0.9, rationale="r")],
            transitions,
        )
        result = publish(session, third)
        assert result.node_count == 2
        assert session.get(CurriculumVersion, first).status == "retired"


# @spec CURR-GRAPH-006
@pytest.mark.parametrize(
    "transition, message",
    [
        (CurriculumTransitionIn(kind="split", from_skills=["a"], to_skills=["b"]), "at least two destination"),
        (CurriculumTransitionIn(kind="merge", from_skills=["a"], to_skills=["b"]), "at least 2 source"),
        (CurriculumTransitionIn(kind="rename", from_skills=["a"], to_skills=["zz"]), "not in this version"),
        (CurriculumTransitionIn(kind="retire", from_skills=["a"], to_skills=["b"]), "exactly 0 destination"),
    ],
)
def test_malformed_transitions_are_refused_at_draft_time(records, transition, message) -> None:
    with sync_session() as session:
        with pytest.raises(ValueError, match=message):
            _draft(session, records, [_concept("a"), _concept("b")], [], [transition])
