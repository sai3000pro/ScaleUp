"""Reading a skill graph for one user.

Node state and proficiency are computed here on every read, never stored. That
is what makes decay continuous and what lets a threshold change take effect
instantly with no backfill and no cron job.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exp import node_level_for_exp
from app.domain.srs import ReviewState, proficiency
from app.domain.states import (
    PREREQ_MASTERY_THRESHOLD,
    NodeState,
    derive_state,
    gating_masteries,
    overdue_days,
)
from app.models import Chunk, Course, NodeProgress, SkillEdge, SkillNode
from app.schemas.graph import (
    GraphEdgeOut,
    GraphNodeOut,
    GraphSnapshot,
    GraphStats,
    NodeProgressOut,
    NodeRef,
    SourceEvidence,
)


def review_state_of(row: NodeProgress | None) -> ReviewState:
    if row is None:
        return ReviewState()
    return ReviewState(
        ease=row.ease,
        interval_days=row.interval_days,
        reps=row.reps,
        lapses=row.lapses,
        mastery=row.mastery,
        last_reviewed_at=row.last_reviewed_at,
        due_at=row.due_at,
    )


async def ensure_progress_rows(session: AsyncSession, user_id: uuid.UUID, node_ids: list[uuid.UUID]) -> None:
    """Backfill missing (user, node) rows.

    Lazy creation on first read keeps the graph endpoint idempotent and means
    ingesting a course does not write a row per node per user who might one day
    open it.
    """
    if not node_ids:
        return
    statement = (
        insert(NodeProgress)
        .values([{"user_id": user_id, "node_id": node_id} for node_id in node_ids])
        .on_conflict_do_nothing(index_elements=["user_id", "node_id"])
    )
    await session.execute(statement)
    await session.commit()


def _source_evidence(
    chunk_ids: list[uuid.UUID] | None,
    chunks_by_id: dict[uuid.UUID, Chunk],
) -> list[SourceEvidence]:
    """Project at most four exact, deterministic source passages."""
    found = [chunks_by_id[chunk_id] for chunk_id in (chunk_ids or []) if chunk_id in chunks_by_id]
    found.sort(key=lambda chunk: (chunk.page_start, chunk.ordinal, str(chunk.id)))
    return [
        SourceEvidence(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            excerpt=" ".join(chunk.text.split())[:320],
        )
        for chunk in found[:4]
    ]


# @spec PROG-STATE-006
def _blocking_prereqs(
    node_id: uuid.UUID,
    prereqs: dict[uuid.UUID, list[uuid.UUID]],
    mastery: dict[uuid.UUID, float],
    assessable: dict[uuid.UUID, bool],
) -> list[uuid.UUID]:
    """Which drillable prerequisites are actually holding this node back.

    Mirrors `gating_masteries` but keeps the ids, so "Needs X" names something
    the user can go and drill rather than a structural heading they cannot.
    """
    blocking: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def walk(current: uuid.UUID) -> None:
        for prereq in prereqs.get(current, ()):
            if prereq in seen:
                pass
            else:
                seen.add(prereq)
                if assessable.get(prereq, True):
                    if mastery.get(prereq, 0.0) < PREREQ_MASTERY_THRESHOLD:
                        blocking.append(prereq)
                else:
                    walk(prereq)

    walk(node_id)
    return blocking


# @spec PROG-STATE-001, PROG-EXP-007
async def build_snapshot(session: AsyncSession, course: Course, user_id: uuid.UUID) -> GraphSnapshot:
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    edges = list(await session.scalars(select(SkillEdge).where(SkillEdge.course_id == course.id)))
    source_ids = {
        chunk_id
        for node in nodes
        for chunk_id in (node.source_chunk_ids or [])
    }
    source_ids.update(
        chunk_id
        for edge in edges
        for chunk_id in (edge.source_chunk_ids or [])
    )
    chunks_by_id = (
        {chunk.id: chunk for chunk in await session.scalars(select(Chunk).where(Chunk.id.in_(source_ids)))}
        if source_ids
        else {}
    )

    await ensure_progress_rows(session, user_id, [node.id for node in nodes])

    progress_rows = {
        row.node_id: row
        for row in await session.scalars(
            select(NodeProgress).where(
                NodeProgress.user_id == user_id,
                NodeProgress.node_id.in_([node.id for node in nodes]) if nodes else False,
            )
        )
    }

    now = datetime.now(timezone.utc)
    states = {node.id: review_state_of(progress_rows.get(node.id)) for node in nodes}
    node_by_id = {node.id: node for node in nodes}

    # Prerequisites come from the FULL edge set, not the reduced one: a
    # transitively implied edge is still a real prerequisite, it is merely not
    # worth drawing.
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {node.id: [] for node in nodes}
    for edge in edges:
        if edge.target_id in prereqs:
            prereqs[edge.target_id].append(edge.prereq_id)

    out_nodes: list[GraphNodeOut] = []
    counts = {state: 0 for state in NodeState}

    # Structural nodes are transparent: they can never be drilled, so their
    # mastery would sit at 0.0 for ever and lock the subtree behind them.
    mastery_by_id = {node_id: state.mastery for node_id, state in states.items()}
    assessable_by_id = {node.id: node.assessable for node in nodes}

    for node in nodes:
        state = states[node.id]
        row = progress_rows.get(node.id)
        level = row.level if row else node_level_for_exp(0)

        prerequisite_masteries = gating_masteries(node.id, prereqs, mastery_by_id, assessable_by_id)
        derived = derive_state(state, level, prerequisite_masteries, now)
        counts[derived] += 1

        # Name the drillable node actually holding this one back, which after
        # resolution may be the structural node's parent rather than the
        # structural node itself.
        blocked_by = [
            NodeRef(id=pid, title=node_by_id[pid].title)
            for pid in _blocking_prereqs(node.id, prereqs, mastery_by_id, assessable_by_id)
            if pid in node_by_id
        ]

        out_nodes.append(
            GraphNodeOut(
                id=node.id,
                slug=node.slug,
                title=node.title,
                summary=node.summary,
                difficulty=node.difficulty,
                depth=node.depth,
                assessable=node.assessable,
                section=node.section,
                progress=NodeProgressOut(
                    state=derived.value,
                    exp=row.exp if row else 0,
                    level=level,
                    mastery=round(state.mastery, 4),
                    proficiency=round(proficiency(state, now), 4),
                    due_at=state.due_at,
                    overdue_days=round(overdue_days(state, now), 3),
                ),
                blocked_by=blocked_by,
                sources=_source_evidence(node.source_chunk_ids, chunks_by_id),
            )
        )

    out_nodes.sort(key=lambda n: (n.depth, n.title))

    return GraphSnapshot(
        course_id=course.id,
        graph_version=course.graph_version,
        nodes=out_nodes,
        # Only the reduced set is rendered; ~40% of extracted edges are
        # transitively implied and drawing them makes a hairball.
        edges=[
            GraphEdgeOut(
                id=f"{edge.prereq_id}->{edge.target_id}",
                source=edge.prereq_id,
                target=edge.target_id,
                confidence=edge.confidence,
                support=edge.support,
                rationale=edge.rationale,
                sources=_source_evidence(edge.source_chunk_ids, chunks_by_id),
            )
            for edge in edges
            if edge.is_reduced
        ],
        stats=GraphStats(
            total=len(nodes),
            locked=counts[NodeState.LOCKED],
            available=counts[NodeState.AVAILABLE],
            learning=counts[NodeState.LEARNING],
            decaying=counts[NodeState.DECAYING],
            mastered=counts[NodeState.MASTERED],
        ),
    )
