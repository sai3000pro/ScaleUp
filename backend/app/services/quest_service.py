"""The Daily Quest board.

Computed per request; there is no `quests` table. The board is a query, which
keeps the endpoint stateless and means a threshold change takes effect instantly
rather than waiting for a nightly job to regenerate rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exp import BASE_AWARD, DIFFICULTY_MULT, rescue_multiplier
from app.domain.srs import proficiency
from app.domain.states import NodeState, derive_state, gating_masteries, overdue_days
from app.models import Course, NodeProgress, SkillEdge, SkillNode, User
from app.schemas.quest import Quest, QuestBoard
from app.services.auth_service import streak_days
from app.services.graph_read import ensure_progress_rows, review_state_of

MAX_OVERDUE = 8
MAX_FRONTIER = 3
MIN_BOARD_SIZE = 3


# @spec PROG-QUEST-003
def _reward(difficulty: int, overdue: float, interval_days: float) -> int:
    """What clearing this quest is worth at full marks, rescue bonus included."""
    multiplier = DIFFICULTY_MULT.get(difficulty, 1.0)
    return int(round(BASE_AWARD * multiplier * rescue_multiplier(overdue, interval_days)))


# @spec PROG-QUEST-001, PROG-QUEST-002, PROG-QUEST-004, PROG-QUEST-005, PROG-QUEST-006
async def build_board(session: AsyncSession, user: User) -> QuestBoard:
    now = datetime.now(timezone.utc)

    # Progress rows are created lazily. Without this backfill a user who opens
    # Quests before ever opening a course sees an empty board -- the exact
    # first-run experience the frontier top-up exists to prevent.
    node_ids = list(
        await session.scalars(
            select(SkillNode.id).join(Course, Course.id == SkillNode.course_id).where(Course.owner_id == user.id)
        )
    )
    await ensure_progress_rows(session, user.id, node_ids)

    # Every node the user has a progress row for, across all their courses.
    rows = list(
        await session.execute(
            select(NodeProgress, SkillNode, Course)
            .join(SkillNode, SkillNode.id == NodeProgress.node_id)
            .join(Course, Course.id == SkillNode.course_id)
            .where(NodeProgress.user_id == user.id, Course.owner_id == user.id)
        )
    )
    if not rows:
        return QuestBoard(date=now.date(), streak_days=0, total_reward_exp=0, quests=[])

    mastery_by_node = {progress.node_id: progress.mastery for progress, _, _ in rows}
    assessable_by_node = {node.id: node.assessable for _, node, _ in rows}

    # Prerequisites, so `frontier` candidates can be filtered to genuinely
    # reachable nodes.
    course_ids = {course.id for _, _, course in rows}
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in await session.scalars(select(SkillEdge).where(SkillEdge.course_id.in_(course_ids))):
        prereqs.setdefault(edge.target_id, []).append(edge.prereq_id)

    overdue_quests: list[tuple[float, int, Quest]] = []
    frontier_quests: list[tuple[int, Quest]] = []

    for progress, node, course in rows:
        state = review_state_of(progress)
        # Structural nodes are transparent; see app/domain/states.py.
        masteries = gating_masteries(node.id, prereqs, mastery_by_node, assessable_by_node)
        derived = derive_state(state, progress.level, masteries, now)

        if not node.assessable:
            # Structural nodes carry the tree's shape but cannot be drilled, so
            # they must never appear on a board the user is asked to clear.
            pass
        elif derived is NodeState.DECAYING:
            days = overdue_days(state, now)
            # Rank by how overdue it is RELATIVE TO ITS OWN INTERVAL. Absolute
            # days would let one ancient 90-day node permanently outrank ten
            # freshly-lapsed ones.
            urgency = days / max(state.interval_days, 0.5)
            overdue_quests.append(
                (
                    urgency,
                    node.depth,
                    Quest(
                        node_id=node.id,
                        node_title=node.title,
                        course_id=course.id,
                        course_title=course.title,
                        reason="overdue",
                        overdue_days=round(days, 2),
                        proficiency=round(proficiency(state, now), 4),
                        due_at=state.due_at,
                        reward_exp=_reward(node.difficulty, days, state.interval_days),
                    ),
                )
            )
        elif derived is NodeState.AVAILABLE and progress.reps == 0:
            frontier_quests.append(
                (
                    node.depth,
                    Quest(
                        node_id=node.id,
                        node_title=node.title,
                        course_id=course.id,
                        course_title=course.title,
                        reason="frontier",
                        overdue_days=0.0,
                        proficiency=0.0,
                        due_at=None,
                        reward_exp=_reward(node.difficulty, 0.0, 0.0),
                    ),
                )
            )

    # Sort to a TOTAL order, not a partial one. Both lists are capped, so any
    # tie left unbroken is decided by the order Postgres happened to return
    # rows in -- which is not stable across requests. With six seeded courses
    # there are many depth-0 roots tied, so the board visibly reshuffled on
    # refresh and a node could drop off between one read and the next.
    # Node id is the final tiebreak: arbitrary, but fixed for a given node.
    overdue_quests.sort(key=lambda item: (-item[0], item[1], str(item[2].node_id)))
    frontier_quests.sort(key=lambda item: (item[0], item[1].course_title, str(item[1].node_id)))

    quests = [quest for _, _, quest in overdue_quests[:MAX_OVERDUE]]

    # Top up so a new user never opens an empty board -- an empty quest screen on
    # day one reads as "this product has nothing for me".
    if len(quests) < MIN_BOARD_SIZE:
        quests.extend(quest for _, quest in frontier_quests[:MAX_FRONTIER])

    return QuestBoard(
        date=now.date(),
        streak_days=await streak_days(session, user.id),
        total_reward_exp=sum(quest.reward_exp for quest in quests),
        quests=quests,
    )
