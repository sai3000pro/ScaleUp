from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.quest import QuestBoard
from app.services import quest_service

router = APIRouter(prefix="/api/quests", tags=["quests"])


@router.get("/daily", response_model=QuestBoard)
async def daily(user: CurrentUser, session: DbSession) -> QuestBoard:
    """Today's board.

    Computed, not stored: overdue skills ranked by how far past due they are
    relative to their own interval, topped up with frontier skills so the board
    is never empty.
    """
    return await quest_service.build_board(session, user)
