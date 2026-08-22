from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.character import CharacterCreate, CharacterSheet, CharacterUpdate
from app.services import character_service

router = APIRouter(prefix="/api/character", tags=["character"])


@router.get("", response_model=CharacterSheet)
async def get_character(user: CurrentUser, session: DbSession) -> CharacterSheet:
    return await character_service.build_sheet(session, user.id, user.total_exp)


@router.post("", response_model=CharacterSheet, status_code=status.HTTP_201_CREATED)
async def create_character(
    payload: CharacterCreate,
    user: CurrentUser,
    session: DbSession,
) -> CharacterSheet:
    await character_service.create_profile(session, user.id, payload)
    return await character_service.build_sheet(session, user.id, user.total_exp)


@router.patch("", response_model=CharacterSheet)
async def update_character(
    payload: CharacterUpdate,
    user: CurrentUser,
    session: DbSession,
) -> CharacterSheet:
    await character_service.update_profile(session, user.id, payload)
    return await character_service.build_sheet(session, user.id, user.total_exp)


@router.post("/perks/{perk_id}", response_model=CharacterSheet)
async def unlock_character_perk(
    perk_id: str,
    user: CurrentUser,
    session: DbSession,
) -> CharacterSheet:
    await character_service.unlock_perk(session, user.id, user.total_exp, perk_id)
    return await character_service.build_sheet(session, user.id, user.total_exp)
