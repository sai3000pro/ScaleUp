"""Published curriculum versions are the only graph input for learner progression."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.models import Chunk, Course, CurriculumVersion, Document, PrerequisiteCandidate, SkillNode, User
from app.services.curriculum_graph_service import EvidenceSpec, create_draft, publish, review_candidate
from app.services.graph_service import ConceptSpec


@pytest.fixture
def curriculum_records(clean_db: None) -> dict[str, uuid.UUID]:
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    with sync_session() as session:
        # These tables are linked by plain FK columns, not ORM relationships, so
        # SQLAlchemy's unit of work has no ordering constraint between them and
        # may flush a child before its parent. Flush at each boundary so the
        # parent row exists before the child insert references it.
        session.add(
            User(id=user_id, email="curriculum@example.com", password_hash="hash", display_name="Curriculum")
        )
        session.flush()
        session.add(Course(id=course_id, owner_id=user_id, title="Violin Source", description="Generated"))
        session.flush()
        session.add(
            Document(
                id=document_id,
                course_id=course_id,
                source_type="text",
                filename="violin.txt",
                content_sha256="1" * 64,
                storage_path="fixture",
                byte_size=100,
                page_count=1,
            )
        )
        session.flush()
        session.add(
            Chunk(
                id=chunk_id,
                document_id=document_id,
                course_id=course_id,
                ordinal=0,
                page_start=1,
                page_end=1,
                section_path="Bow Hold",
                text="Prerequisites: instrument-setup. Shape the bow hand with a flexible thumb.",
                token_count=12,
                content_sha256="2" * 64,
            )
        )
    return {"user_id": user_id, "course_id": course_id, "chunk_id": chunk_id}


async def test_draft_is_inert_until_review_and_publication(curriculum_records: dict[str, uuid.UUID]) -> None:
    concepts = [
        ConceptSpec(
            "instrument-setup",
            "Instrument Setup",
            "Hold the violin safely.",
            1,
            source_chunk_ids=(curriculum_records["chunk_id"],),
        ),
        ConceptSpec(
            "bow-hold",
            "Bow Hold",
            "Shape the bow hand.",
            2,
            source_chunk_ids=(curriculum_records["chunk_id"],),
        ),
    ]
    with sync_session() as session:
        course = session.get(Course, curriculum_records["course_id"])
        draft = create_draft(
            session,
            course,
            "violin",
            "Violin",
            "violin-foundations",
            "Violin Foundations",
            concepts,
            [CandidateEdge("instrument-setup", "bow-hold", 0.9, rationale="Prerequisites: instrument-setup")],
            {
                ("instrument-setup", "bow-hold"): [
                    EvidenceSpec(curriculum_records["chunk_id"], "Prerequisites: instrument-setup")
                ]
            },
        )
        assert session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)).all() == []
        version = session.get(CurriculumVersion, draft.version_id)
        candidate = version and session.scalar(
            select(PrerequisiteCandidate).where(PrerequisiteCandidate.curriculum_version_id == version.id)
        )
        # create_draft promotes the version to "review" when it has accepted
        # candidates; the candidates themselves stay "draft" until reviewed.
        assert version.status == "review"
        assert candidate.status == "draft"
        # A draft is inert: publishing while a candidate is unreviewed is rejected.
        with pytest.raises(ValueError, match="Every curriculum candidate"):
            publish(session, version.id)
        review_candidate(session, version.id, candidate.id, curriculum_records["user_id"], "accepted", "Evidence is direct.")

        result = publish(session, version.id)
        nodes = list(session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
        assert result.node_count == 2
        assert result.edge_count == 1
        assert all(node.curriculum_version_id == version.id for node in nodes)
        assert all(node.skill_definition_id is not None for node in nodes)
