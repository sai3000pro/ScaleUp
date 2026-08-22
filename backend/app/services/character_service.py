from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.character import achievement_rows, calculate_stats, perk_definitions
from app.domain.exp import level_progress
from app.models import Attempt, CharacterProfile, Course, NodeProgress
from app.schemas.character import (
    AchievementOut,
    CharacterCreate,
    CharacterPerkOut,
    CharacterProfileOut,
    CharacterSheet,
    CharacterStatsOut,
    CharacterUpdate,
)
from app.services.auth_service import streak_days


async def _profile(session: AsyncSession, user_id: uuid.UUID) -> CharacterProfile | None:
    return await session.get(CharacterProfile, user_id)


async def _learning_facts(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int | float]:
    attempts = list(await session.scalars(select(Attempt).where(Attempt.user_id == user_id, Attempt.status == "graded")))
    progress_rows = list(await session.scalars(select(NodeProgress).where(NodeProgress.user_id == user_id)))
    course_count = await session.scalar(select(func.count(Course.id)).where(Course.owner_id == user_id)) or 0
    scores = [float(attempt.score or 0.0) for attempt in attempts]
    started = sum(1 for progress in progress_rows if progress.reps > 0 or progress.last_reviewed_at is not None)
    mastered = sum(1 for progress in progress_rows if progress.level >= 5 and progress.mastery >= 0.8)
    rescued = sum(1 for attempt in attempts if attempt.rescue_bonus_applied)
    return {
        "attempts": len(attempts),
        "average_score": sum(scores) / len(scores) if scores else 0.0,
        "started_skills": started,
        "mastered_skills": mastered,
        "course_count": int(course_count),
        "rescue_count": rescued,
    }


# @spec PROG-META-001, PROG-STATE-007
async def build_sheet(session: AsyncSession, user_id: uuid.UUID, total_exp: int) -> CharacterSheet:
    profile = await _profile(session, user_id)
    level, exp_into_level, exp_for_next_level = level_progress(total_exp)
    facts = await _learning_facts(session, user_id)
    current_streak = await streak_days(session, user_id)
    unlocked = set(profile.unlocked_perks if profile else [])
    stats = calculate_stats(
        level=level,
        streak_days=current_streak,
        average_score=float(facts["average_score"]),
        started_skills=int(facts["started_skills"]),
        mastered_skills=int(facts["mastered_skills"]),
        course_count=int(facts["course_count"]),
        rescue_count=int(facts["rescue_count"]),
        unlocked_perks=unlocked,
    )
    perks = [CharacterPerkOut(**perk) for perk in perk_definitions(unlocked)]
    achievements = [
        AchievementOut(**achievement)
        for achievement in achievement_rows(
            attempts=int(facts["attempts"]),
            started_skills=int(facts["started_skills"]),
            mastered_skills=int(facts["mastered_skills"]),
            streak_days=current_streak,
            rescue_count=int(facts["rescue_count"]),
            unlocked_perks=len(unlocked),
        )
    ]
    profile_out = CharacterProfileOut.model_validate(profile) if profile else None
    return CharacterSheet(
        profile=profile_out,
        level=level,
        total_exp=total_exp,
        exp_into_level=exp_into_level,
        exp_for_next_level=exp_for_next_level,
        streak_days=current_streak,
        stats=CharacterStatsOut.model_validate(stats),
        perks=perks,
        achievements=achievements,
        available_perk_points=max(0, level - len(unlocked)),
    )


async def create_profile(session: AsyncSession, user_id: uuid.UUID, payload: CharacterCreate) -> CharacterProfile:
    existing = await _profile(session, user_id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your character already exists.")
    profile = CharacterProfile(
        user_id=user_id,
        character_name=payload.character_name.strip(),
        avatar_key=payload.avatar_key,
        archetype=payload.archetype,
        skin_tone=payload.skin_tone,
        hair_style=payload.hair_style,
        hair_color=payload.hair_color,
        outfit_color=payload.outfit_color,
        accessory=payload.accessory,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: CharacterUpdate,
) -> CharacterProfile:
    profile = await _profile(session, user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your character first.")
    if payload.character_name is not None:
        profile.character_name = payload.character_name.strip()
    if payload.avatar_key is not None:
        profile.avatar_key = payload.avatar_key
    if payload.archetype is not None:
        profile.archetype = payload.archetype
    if payload.skin_tone is not None:
        profile.skin_tone = payload.skin_tone
    if payload.hair_style is not None:
        profile.hair_style = payload.hair_style
    if payload.hair_color is not None:
        profile.hair_color = payload.hair_color
    if payload.outfit_color is not None:
        profile.outfit_color = payload.outfit_color
    if payload.accessory is not None:
        profile.accessory = payload.accessory
    await session.commit()
    await session.refresh(profile)
    return profile


# @spec PROG-META-002
async def unlock_perk(
    session: AsyncSession,
    user_id: uuid.UUID,
    total_exp: int,
    perk_id: str,
) -> CharacterProfile:
    profile = await _profile(session, user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your character first.")
    catalog = {perk["id"] for perk in perk_definitions(set())}
    if perk_id not in catalog:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That character perk does not exist.")
    unlocked = list(profile.unlocked_perks or [])
    if perk_id in unlocked:
        return profile
    level = level_progress(total_exp)[0]
    if len(unlocked) >= level:
        raise HTTPException(status.HTTP_409_CONFLICT, "Earn another account level before unlocking a perk.")
    unlocked.append(perk_id)
    profile.unlocked_perks = unlocked
    await session.commit()
    await session.refresh(profile)
    return profile
