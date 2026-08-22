"""Goal-first construction: a learner's sentence becomes a published tree.

One request, no document, no ingest, no background job. The learner types "I want
to learn how to play guitar" and gets a playable prerequisite graph back.

Three things happen here, and the order matters.

**The instrument is read from the goal.** A sentence is what a learner arrives
with; a dropdown caps the product at what it already knows.

**The tree is assembled or proposed.** An instrument this project ships a reviewed
curriculum for *is already answered* — that curriculum is used and no model is
asked. Anything else goes to the planning role with the whole catalogue as a closed
vocabulary, and the returned plan is validated before a row is written.

**A rejected plan falls back rather than failing.** The deterministic assembly is
always available, so a bad proposal, a provider outage or an exhausted budget costs
the learner instrument-specific detail, never their tree.

Everything lands through `seed_published_curriculum`, the same call the seed and the
document compiler use, so a goal-built tree is the same shape as every other tree.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.curricula.loader import CurriculumDefinition
from app.curricula.planner import (
    PlanValidationError,
    assemble,
    catalogue_prompt_payload,
    definition_from_plan,
    known_instruments,
    resolve_instrument,
)
from app.llm.base import LLMError, LLMRole
from app.models.course import Course
from app.models.user import User
from app.schemas.course import CourseOut
from app.services import course_service
from app.services.curriculum_graph_service import EvidenceSpec, seed_published_curriculum
from app.services.graph_service import ConceptSpec
from app.services.llm_gateway import recording_llm_client

logger = logging.getLogger(__name__)

#: How a curriculum version was built. Recorded on the version so a learner can be
#: told the difference between a tree this project authored and one it proposed.
ASSEMBLED = "catalogue-assembly-v1"
PROPOSED = "catalogue-plan-v1"


class GoalNotUnderstoodError(ValueError):
    """The goal names nothing playable, so there is no tree to build."""


def _concept_specs(definition: CurriculumDefinition) -> list[ConceptSpec]:
    return [
        ConceptSpec(
            slug=concept.slug,
            title=concept.title,
            summary=concept.summary,
            difficulty=concept.difficulty,
            key_terms=concept.key_terms,
        )
        for concept in definition.concepts
    ]


async def _propose(goal: str, instrument: str, course_id: uuid.UUID) -> tuple[CurriculumDefinition, str]:
    """Ask the planning role for a tree, and take it only if it validates."""
    client = recording_llm_client(course_id)
    try:
        result = await client.structured(
            LLMRole.CURRICULUM_PLAN,
            {
                "goal": goal,
                "instrument": instrument,
                "catalogue": catalogue_prompt_payload(),
            },
            course_id=str(course_id),
        )
    except LLMError as exc:
        logger.warning("curriculum plan unavailable for %r (%s); assembling instead", instrument, exc)
        return assemble(instrument), ASSEMBLED

    try:
        return definition_from_plan(result.data, instrument=instrument), PROPOSED
    except PlanValidationError as exc:
        # Refused whole, never repaired: a patched plan is a tree nobody authored
        # and nobody proposed. The learner still gets the catalogue spine.
        logger.warning("curriculum plan for %r rejected (%s); assembling instead", instrument, exc)
        return assemble(instrument), ASSEMBLED


# @spec CURR-GOAL-001, CURR-GOAL-002, CURR-GOAL-003, CURR-GOAL-004, CURR-GOAL-005
# @spec CURR-GOAL-006, CURR-GOAL-011, CURR-GOAL-012, CURR-GOAL-016, CURR-GOAL-018
async def create_course_from_goal(session: AsyncSession, user: User, goal: str) -> CourseOut:
    """Build and publish a course for a stated goal, in one request."""
    instrument = resolve_instrument(goal)
    if instrument is None:
        raise GoalNotUnderstoodError(
            "Name an instrument you want to learn — for example, "
            "\"I want to learn how to play guitar\"."
        )

    course = Course(
        owner_id=user.id,
        title=" ".join(word.capitalize() for word in instrument.split()),
        description=f"A skill tree for learning {instrument}, built from your goal: “{goal.strip()}”.",
        status="draft",
    )
    session.add(course)

    if instrument in known_instruments():
        # Already authored and reviewed. A model has nothing to add to it.
        await session.flush()
        definition, provenance = assemble(instrument), ASSEMBLED
    else:
        # Committed before the model is asked, not merely flushed. The ledger
        # writes from its own session, so an uncommitted course is a course that
        # session cannot see -- and `llm_calls.course_id` is a foreign key, so the
        # row is refused and the spend for every goal-built tree goes unrecorded.
        # A tree that then fails to build leaves a draft course, which is visible
        # and recoverable; a spend nobody recorded is neither.
        await session.commit()
        await session.refresh(course)
        definition, provenance = await _propose(goal, instrument, course.id)

    specs = _concept_specs(definition)
    edges = list(definition.edges)
    evidence: dict[tuple[str, str], tuple[EvidenceSpec, ...]] = {}

    await session.run_sync(
        lambda sync: seed_published_curriculum(
            sync,
            course,
            definition.instrument,
            definition.title,
            f"{definition.slug}-{course.id.hex[:8]}",
            definition.title,
            specs,
            edges,
            evidence,
            user.id,
            compiler_version=provenance,
        )
    )
    course.status = "ready"
    await session.commit()
    await session.refresh(course)
    return await course_service.project(session, course, user.id)
