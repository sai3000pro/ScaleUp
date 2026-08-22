"""Turning a skill node into something the learner can actually play.

A node without an exercise is an orb you can look at. The five checked-in
MusicXML constants cover five nodes out of the fifty-odd the shipped curricula
define, so most of the tree was decorative. This service closes that: every
playable node gets a generated score, and generation is idempotent, so running
it again is a no-op rather than a duplicate.

Two entry shapes, deliberately:

* `ensure_exercise_for_node` is synchronous and **procedural only**. It runs
  inside the seed and inside curriculum publication, both of which are sync
  paths driven through `core/sync_bridge.py`. Publication must stay
  deterministic and offline -- a provider outage or an exhausted course budget
  mid-publish would abort a graph write, which is a far worse failure than a
  plainer exercise.
* `create_exercise_for_node` is async, serves the API, and may ask the
  `SCORE_COMPOSE` role for something more musical. Every failure there keeps the
  procedural floor, so the endpoint cannot fail for a reason the learner would
  have to care about.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Mapping

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.evaluation.musicxml import midi_to_note_name, parse_musicxml
from app.evaluation.score_generator import (
    INSTRUMENT_PROFILES,
    MAX_NOTES,
    GeneratedScore,
    ScoreGenerationError,
    ScoreSpec,
    compose_score,
    generate_score,
    spec_for_node,
)
from app.llm.base import BudgetExceededError, LLMRole, RefusalError, SchemaValidationError
from app.models import Course, Exercise, ScoreAsset, SkillNode
from app.models.curriculum_graph import CurriculumVersion, Instrument
from app.schemas.performance import ExerciseGenerateIn, ExerciseNoteOut, ExerciseOut
from app.services.llm_gateway import recording_llm_client

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = (
    "Play the written exercise at a steady tempo. Record the whole phrase, then submit it for scoring."
)


def _instructions_for(generated: GeneratedScore) -> str:
    spec = generated.spec
    profile = INSTRUMENT_PROFILES[spec.instrument]
    if not profile.pitched:
        return (
            f"Play {spec.bars} bars of the written groove at {spec.tempo_bpm} BPM. "
            "Keep the pulse even -- the scorer reads timing and drum identity, not pitch."
        )
    return (
        f"Play the written exercise in {spec.tonic} {spec.mode} at {spec.tempo_bpm} BPM, "
        f"{spec.bars} bar{'s' if spec.bars != 1 else ''}. Keep a steady pulse and let each note speak."
    )


def _score_title(generated: GeneratedScore) -> str:
    return generated.spec.title[:200]


# @spec EVAL-GEN-007
def persist_score_asset(
    session: Session,
    *,
    course_id: uuid.UUID,
    generated: GeneratedScore,
    asset_id: uuid.UUID | None = None,
) -> ScoreAsset:
    """Store a generated score, reusing an identical one if it already exists.

    `score_assets` already carries `UNIQUE (course_id, content_sha256)`, so
    content addressing is the idempotency key and no bookkeeping is needed:
    regenerating the same exercise twice cannot produce two rows.
    """
    parsed = parse_musicxml(generated.musicxml)
    digest = hashlib.sha256(generated.musicxml.encode("utf-8")).hexdigest()

    existing = session.scalar(
        select(ScoreAsset).where(ScoreAsset.course_id == course_id, ScoreAsset.content_sha256 == digest)
    )
    if existing is not None:
        return existing

    asset = ScoreAsset(
        id=asset_id or uuid.uuid4(),
        course_id=course_id,
        title=_score_title(generated),
        format="musicxml",
        content=generated.musicxml,
        content_sha256=digest,
        tempo_bpm=parsed.tempo_bpm,
        duration_beats=parsed.duration_beats,
        asset_metadata=generated.asset_metadata,
    )
    session.add(asset)
    try:
        session.flush()
    except IntegrityError:
        # Another writer won the race on the content hash. The row it wrote is
        # byte-identical by definition, so adopting it loses nothing.
        session.rollback()
        winner = session.scalar(
            select(ScoreAsset).where(ScoreAsset.course_id == course_id, ScoreAsset.content_sha256 == digest)
        )
        if winner is None:
            raise
        return winner
    return asset


# @spec EVAL-GEN-008
def ensure_exercise_for_node(
    session: Session,
    *,
    course: Course,
    node: SkillNode,
    instrument: str,
    overrides: Mapping[str, object] | None = None,
    exercise_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
) -> Exercise | None:
    """Give `node` a playable exercise if it does not already have one.

    Returns the existing exercise untouched when there is one. Regeneration is
    deliberately not offered here: an attempt's history is grouped by exercise,
    so swapping the score under a stable id turns "you improved" into a
    comparison between two different pieces of music.
    """
    if not node.assessable:
        return None

    spec = spec_for_node(
        instrument=instrument,
        node_slug=node.slug,
        node_title=node.title,
        difficulty=node.difficulty,
        overrides=overrides,
    )
    slug = f"{node.slug}-{spec.pattern}"[:80]
    existing = session.scalar(
        select(Exercise).where(Exercise.course_id == course.id, Exercise.slug == slug)
    )
    if existing is not None:
        return existing

    return _create_exercise(
        session,
        course=course,
        node=node,
        spec=spec,
        slug=slug,
        title=spec.title,
        difficulty=node.difficulty,
        exercise_id=exercise_id,
        asset_id=asset_id,
    )


def _create_exercise(
    session: Session,
    *,
    course: Course,
    node: SkillNode,
    spec,
    slug: str,
    title: str,
    difficulty: int,
    exercise_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
) -> Exercise | None:
    try:
        generated = generate_score(spec)
    except ScoreGenerationError:
        # A node whose title and difficulty cannot be turned into something
        # playable on this instrument is a curriculum question, not a crash.
        logger.warning("no playable exercise for node %s on %s", node.slug, spec.instrument, exc_info=True)
        return None

    asset = persist_score_asset(session, course_id=course.id, generated=generated, asset_id=asset_id)
    exercise = Exercise(
        id=exercise_id or uuid.uuid4(),
        course_id=course.id,
        node_id=node.id,
        score_asset_id=asset.id,
        slug=slug,
        title=title,
        instructions=_instructions_for(generated),
        evaluator_version=generated.evaluator_version,
        difficulty=difficulty,
        active=True,
    )
    session.add(exercise)
    session.flush()
    return exercise


#: How many graded lessons a skill gets. Three is the smallest number that makes
#: a chain rather than a pair: something to start on, something that is the skill
#: at its stated difficulty, and something that is harder than the skill.
LESSONS_PER_SKILL = 3


# @spec CURR-VERSION-011
def ensure_lesson_set_for_node(
    session: Session,
    *,
    course: Course,
    node: SkillNode,
    instrument: str,
    overrides: Mapping[str, object] | None = None,
) -> list[Exercise]:
    """Give `node` a graded run of lessons rather than a single exercise.

    A skill is not one thing you either can or cannot do. "Basic Strumming" is a
    slow four-bar pattern before it is a fast eight-bar one, and a learner needs
    somewhere to stand between never having tried it and being tested on it.

    The steps differ where it matters: difficulty drives tempo and length in
    `spec_for_node`, so lesson one is genuinely slower and shorter than lesson
    three. They are not three renderings of the same score.

    Idempotent, and backward-compatible by construction: the first lesson keeps
    the slug a single exercise already used, so a node generated before this
    existed becomes lesson one rather than gaining a fourth sibling.
    """
    if not node.assessable:
        return []

    lessons: list[Exercise] = []
    for step in range(1, LESSONS_PER_SKILL + 1):
        # The run STARTS at the skill's own difficulty and climbs from there.
        # Centring it instead would put lesson one below the skill, which reads
        # better on paper and is wrong in practice: a node generated before
        # lesson runs existed already carries the skill's difficulty, and it
        # becomes lesson one. Relabelling it as easier would make the label lie
        # about music that is already written and already has attempts against it.
        graded = max(1, min(5, node.difficulty + step - 1))
        spec = spec_for_node(
            instrument=instrument,
            node_slug=node.slug,
            node_title=node.title,
            difficulty=graded,
            overrides=overrides,
        )
        base = f"{node.slug}-{spec.pattern}"
        slug = base if step == 1 else f"{base}-{step}"
        title = f"{node.title} {step}"

        existing = session.scalar(
            select(Exercise).where(Exercise.course_id == course.id, Exercise.slug == slug[:80])
        )
        if existing is not None:
            # Only the name is reconciled. The SCORE is never regenerated under a
            # stable id -- attempt history is grouped by exercise, and swapping
            # the music turns "you improved" into a comparison of two pieces.
            existing.title = title
            lessons.append(existing)
        else:
            created = _create_exercise(
                session, course=course, node=node, spec=spec, slug=slug[:80], title=title, difficulty=graded
            )
            if created is not None:
                lessons.append(created)

    session.flush()
    return lessons


def instrument_for_course(session: Session, course_id: uuid.UUID) -> str | None:
    """The instrument a course's published curriculum is for, if it has one.

    Textbook courses have no instrument and no playable exercises; returning
    None rather than defaulting to piano is what keeps a linear-algebra course
    from sprouting scales.
    """
    return session.scalar(
        select(Instrument.slug)
        .join(CurriculumVersion, CurriculumVersion.instrument_id == Instrument.id)
        .join(SkillNode, SkillNode.curriculum_version_id == CurriculumVersion.id)
        .where(SkillNode.course_id == course_id)
        .limit(1)
    )


def _procedural_note_payload(generated: GeneratedScore) -> str:
    """The floor's notes, as the JSON the prompt shows the model.

    The fake provider reads this back and echoes it, which is what lets a no-key
    run walk the whole compose path and still end up with a real, playable
    score.
    """
    payload = []
    for note in generated.notes:
        entry: dict[str, object] = {"beats": float(note.duration_beats)}
        if note.drum is not None:
            entry["drum"] = note.drum
        elif note.step is None:
            entry["step"] = None
        else:
            entry["step"] = note.step
            entry["alter"] = note.alter
            entry["octave"] = note.octave
        if note.chord:
            entry["chord"] = True
        payload.append(entry)
    return json.dumps(payload)


def _constraints_for(spec: ScoreSpec) -> str:
    profile = INSTRUMENT_PROFILES[spec.instrument]
    lines = [
        f"- At most {MAX_NOTES} notes.",
        f"- Every bar holds exactly {spec.beats_per_measure * 4 // spec.beat_type} beats.",
    ]
    if profile.pitched:
        lines.append(f"- Playable range: MIDI {profile.lowest_midi} to {profile.highest_midi}.")
        lines.append(
            f"- This instrument is {'polyphonic' if profile.polyphonic else 'monophonic'}: "
            f"{'chords are allowed' if profile.polyphonic else 'never set chord'}."
        )
        lines.append("- Never send a `drum` field.")
    else:
        lines.append("- Percussion: every note carries `drum` and never `step`.")
    return "\n".join(lines)


# @spec EVAL-GEN-005, EVAL-GEN-006
async def _compose_with_llm(spec: ScoreSpec, node: SkillNode, course_id: uuid.UUID) -> GeneratedScore:
    floor = generate_score(spec)
    client = recording_llm_client(course_id)
    variables = {
        "skill_title": node.title,
        "skill_summary": node.summary,
        "instrument": spec.instrument,
        "pattern": str(spec.pattern),
        "key": f"{spec.tonic} {spec.mode}",
        "tempo_bpm": spec.tempo_bpm,
        "time_signature": f"{spec.beats_per_measure}/{spec.beat_type}",
        "beats_per_bar": spec.beats_per_measure * 4 // spec.beat_type,
        "bars": spec.bars,
        "difficulty": spec.difficulty,
        "constraints": _constraints_for(spec),
        "procedural_notes": _procedural_note_payload(floor),
    }
    try:
        result = await client.structured(LLMRole.SCORE_COMPOSE, variables, course_id=str(course_id))
    except (BudgetExceededError, RefusalError, SchemaValidationError) as exc:
        # A course at its spend ceiling, a refusal, or an unparseable response
        # all mean the same thing here: keep the floor. Surfacing a 402 or a 502
        # from "give this node an exercise" would be a worse product than a
        # plainer scale.
        logger.info("score compose fell back to the procedural floor: %s", exc)
        return floor
    except Exception:
        logger.warning("score compose failed; keeping the procedural floor", exc_info=True)
        return floor
    return compose_score(spec, result.data)


async def create_exercise_for_node(
    session: AsyncSession,
    *,
    course: Course,
    payload: ExerciseGenerateIn,
) -> tuple[ExerciseOut, bool]:
    """Generate and attach an exercise to one node. Returns (exercise, created)."""
    node = await session.get(SkillNode, payload.node_id)
    if node is None or node.course_id != course.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found.")
    if not node.assessable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This skill is structural and cannot be practised.")

    instrument = payload.instrument or await _instrument_for_course_async(session, course.id)
    if instrument is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This course has no instrument, so it has no playable exercises. Name one explicitly to override.",
        )
    if instrument not in INSTRUMENT_PROFILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown instrument: {instrument!r}.")

    overrides = payload.model_dump(exclude={"node_id", "use_llm", "instrument"}, exclude_none=True)
    try:
        spec = spec_for_node(
            instrument=instrument,
            node_slug=node.slug,
            node_title=node.title,
            difficulty=node.difficulty,
            overrides=overrides,
        )
    except (ScoreGenerationError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    slug = f"{node.slug}-{spec.pattern}"[:80]
    existing = await session.scalar(
        select(Exercise).where(Exercise.course_id == course.id, Exercise.slug == slug)
    )
    if existing is not None:
        asset = await session.get(ScoreAsset, existing.score_asset_id)
        return _exercise_out(existing, asset), False

    try:
        generated = await _compose_with_llm(spec, node, course.id) if payload.use_llm else generate_score(spec)
    except ScoreGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    digest = hashlib.sha256(generated.musicxml.encode("utf-8")).hexdigest()
    asset = await session.scalar(
        select(ScoreAsset).where(ScoreAsset.course_id == course.id, ScoreAsset.content_sha256 == digest)
    )
    if asset is None:
        parsed = parse_musicxml(generated.musicxml)
        asset = ScoreAsset(
            course_id=course.id,
            title=_score_title(generated),
            format="musicxml",
            content=generated.musicxml,
            content_sha256=digest,
            tempo_bpm=parsed.tempo_bpm,
            duration_beats=parsed.duration_beats,
            asset_metadata=generated.asset_metadata,
        )
        session.add(asset)
        await session.flush()

    exercise = Exercise(
        course_id=course.id,
        node_id=node.id,
        score_asset_id=asset.id,
        slug=slug,
        title=spec.title,
        instructions=_instructions_for(generated),
        evaluator_version=generated.evaluator_version,
        difficulty=node.difficulty,
        active=True,
    )
    session.add(exercise)
    await session.commit()
    await session.refresh(exercise)
    return _exercise_out(exercise, asset), True


async def _instrument_for_course_async(session: AsyncSession, course_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(Instrument.slug)
        .join(CurriculumVersion, CurriculumVersion.instrument_id == Instrument.id)
        .join(SkillNode, SkillNode.curriculum_version_id == CurriculumVersion.id)
        .where(SkillNode.course_id == course_id)
        .limit(1)
    )


def _notes_from_score(content: str) -> list[ExerciseNoteOut]:
    try:
        score = parse_musicxml(content)
        result = []
        for n in score.notes:
            if n.pitch_midi is not None:
                name = midi_to_note_name(n.pitch_midi)
            elif n.unpitched_step:
                name = f"{n.unpitched_step}{n.unpitched_octave or ''}"
            else:
                name = "Rest"
            result.append(
                ExerciseNoteOut(
                    pitch_midi=n.pitch_midi,
                    note_name=name,
                    onset_beats=n.onset_beats,
                    duration_beats=n.duration_beats,
                    fret=n.fret,
                    string=n.string,
                )
            )
        return result
    except Exception:
        return []


def _exercise_out(exercise: Exercise, asset: ScoreAsset | None) -> ExerciseOut:
    return ExerciseOut(
        id=exercise.id,
        course_id=exercise.course_id,
        node_id=exercise.node_id,
        slug=exercise.slug,
        title=exercise.title,
        instructions=exercise.instructions,
        score_title=asset.title if asset is not None else exercise.title,
        score_format=asset.format if asset is not None else "musicxml",
        tempo_bpm=asset.tempo_bpm if asset is not None else 0.0,
        duration_beats=asset.duration_beats if asset is not None else 0.0,
        evaluator_version=exercise.evaluator_version,
        difficulty=exercise.difficulty,
        notes=_notes_from_score(asset.content) if asset is not None else [],
    )
