"""Question generation and semantic grading.

Both halves run through the LLM seam, so `LLM_PROVIDER=fake` exercises the whole
loop with no keys and no spend.

Grading is the one place a user directly judges the product, so two properties
matter more than anything else here:

* **it must not double-award** -- grading an already-graded attempt returns the
  stored result verbatim, making a retry on a flaky connection safe;
* **the feedback must be specific** -- that requirement lives in the prompt, and
  the rubric ids that survive into `attempts` are what make it auditable later.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.domain.exp import account_level_for_exp, award_for_attempt, node_level_for_exp
from app.domain.srs import proficiency, schedule
from app.domain.states import (
    PREREQ_MASTERY_THRESHOLD,
    NodeState,
    derive_state,
    gating_masteries,
    overdue_days,
)
from app.llm.base import BudgetExceededError, LLMRole
from app.llm.registry import ROLES
from app.models import Attempt, Chunk, NodeProgress, Question, SkillEdge, SkillNode, User
from app.schemas.drill import DrillOut, GradeResult, QuestionOption, QuestionType, SourceRef
from app.schemas.graph import NodeProgressOut
from app.services.graph_read import ensure_progress_rows, review_state_of
from app.services.llm_gateway import embed_texts_recorded, recording_llm_client
from app.vector.chroma_store import get_vector_store

RETRIEVAL_K = 5


async def _load_node(session: AsyncSession, node_id: uuid.UUID, user_id: uuid.UUID) -> SkillNode:
    node = await session.get(SkillNode, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found.")

    # Ownership runs through the course, so a node id from another user's course
    # is a 404 rather than a 403 -- a 403 would confirm the id exists.
    from app.models import Course

    course = await session.get(Course, node.course_id)
    if course is None or course.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found.")
    return node


async def _course_gating(
    session: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], dict[uuid.UUID, float], dict[uuid.UUID, bool]]:
    """Everything needed to decide what is locked, for one course.

    Loaded course-wide rather than per-node because a structural node is
    resolved by walking through it to ITS prerequisites, which can be any
    distance up the tree -- see `app.domain.states.gating_masteries`.
    """
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in await session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id)):
        prereqs.setdefault(edge.target_id, []).append(edge.prereq_id)

    assessable = {
        node_id: flag
        for node_id, flag in await session.execute(
            select(SkillNode.id, SkillNode.assessable).where(SkillNode.course_id == course_id)
        )
    }
    mastery = {
        row.node_id: row.mastery
        for row in await session.scalars(
            select(NodeProgress).where(
                NodeProgress.user_id == user_id, NodeProgress.node_id.in_(assessable.keys())
            )
        )
    }
    return prereqs, mastery, assessable


async def _prerequisite_masteries(session: AsyncSession, node: SkillNode, user_id: uuid.UUID) -> list[float]:
    prereqs, mastery, assessable = await _course_gating(session, node.course_id, user_id)
    return gating_masteries(node.id, prereqs, mastery, assessable)


# @spec CURR-PROJ-007
async def _retrieve_context(session: AsyncSession, node: SkillNode) -> list[Chunk]:
    """Chunks the question should be drawn from.

    Prefers the node's own provenance (the chunks it was extracted from) and
    tops up with semantic neighbours. Provenance first matters: a question
    generated from loosely-related passages tests something the node does not
    claim to teach.

    A course compiled from a curriculum rather than ingested from a document has
    no chunks at all, and six of the courses this project ships are exactly that.
    The top-up below cannot return anything for one of them, but it still costs an
    embedding, a ledger row, and a round trip to the vector store -- on the
    request a learner is watching, and on a host where the vector store may not be
    deployed and the round trip is a connection that has to time out before the
    `except` can swallow it. So the cheap question is asked first: does this
    course have any source material?
    """
    chunks: list[Chunk] = []
    if node.source_chunk_ids:
        chunks = list(await session.scalars(select(Chunk).where(Chunk.id.in_(node.source_chunk_ids))))

    if len(chunks) < RETRIEVAL_K and await _course_has_source_material(session, node.course_id):
        try:
            # Off the event loop: both the embedding call and the ledger write it
            # now performs are blocking, and this runs inside `POST /drill`.
            [vector] = await run_in_threadpool(
                embed_texts_recorded, [f"{node.title}. {node.summary}"], course_id=node.course_id
            )
            hits = get_vector_store().query(str(node.course_id), vector, k=RETRIEVAL_K)
            extra_ids = [uuid.UUID(hit.chunk_id) for hit in hits if uuid.UUID(hit.chunk_id) not in {c.id for c in chunks}]
            if extra_ids:
                chunks.extend(await session.scalars(select(Chunk).where(Chunk.id.in_(extra_ids))))
        except BudgetExceededError:
            raise
        except Exception:  # noqa: BLE001 -- retrieval is a top-up; provenance alone is usable
            pass

    return chunks[:RETRIEVAL_K]


async def _course_has_source_material(session: AsyncSession, course_id: uuid.UUID) -> bool:
    """Whether anything was ever ingested for this course.

    One indexed existence check against Postgres, which is already open, in place
    of an embedding and a network round trip to a store that would answer empty.
    """
    return bool(
        await session.scalar(select(Chunk.id).where(Chunk.course_id == course_id).limit(1))
    )


def _render_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.section_path or 'source'}]\n{c.text}" for c in chunks) or "(no source material available)"


async def start_drill(
    session: AsyncSession,
    node_id: uuid.UUID,
    user: User,
    idempotency_key: str | None,
    question_type: QuestionType = "short_answer",
) -> DrillOut:
    node = await _load_node(session, node_id, user.id)

    if not node.assessable:
        raise HTTPException(status.HTTP_409_CONFLICT, "This node carries structure but cannot be drilled.")

    await ensure_progress_rows(session, user.id, [node.id])
    progress = await session.get(NodeProgress, (user.id, node.id))
    state = derive_state(
        review_state_of(progress),
        progress.level if progress else 0,
        await _prerequisite_masteries(session, node, user.id),
        datetime.now(timezone.utc),
    )
    if state is NodeState.LOCKED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish this skill's prerequisites first.")

    # Idempotency: the same key returns the same attempt rather than paying for
    # another generation call.
    if idempotency_key:
        existing = await session.scalar(
            select(Attempt).where(Attempt.user_id == user.id, Attempt.idempotency_key == idempotency_key)
        )
        if existing is None:
            pass
        else:
            existing_question = await session.get(Question, existing.question_id)
            if existing.node_id != node.id or (existing_question and existing_question.question_type != question_type):
                # The uniqueness constraint is (user_id, idempotency_key) with no
                # node or format, so a client reusing one key for another skill or
                # format would otherwise receive the wrong attempt.
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "That Idempotency-Key was already used for a different drill. Use a fresh key.",
                )
            return await _project_drill(session, existing, existing_question, node)

    chunks = await _retrieve_context(session, node)
    client = recording_llm_client(node.course_id)
    result = await client.structured(
        LLMRole.QUESTION_GEN,
        {
            "node_title": node.title,
            "node_summary": node.summary,
            "context": _render_context(chunks),
            "requested_type": question_type,
        },
        course_id=str(node.course_id),
    )

    generated_type = result.data["question_type"]
    generated_options = result.data.get("options") or []
    generated_correct = result.data.get("correct_option_id")
    accepted_answers = [str(answer).strip() for answer in (result.data.get("accepted_answers") or []) if str(answer).strip()]
    code_language = result.data.get("code_language")
    code_requirements = [str(item).strip() for item in (result.data.get("code_requirements") or []) if str(item).strip()]
    option_ids = [str(option["id"]) for option in generated_options]
    if generated_type != question_type:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The question generator returned the wrong format.")
    if question_type == "mcq" and (
        len(generated_options) != 4
        or len(set(option_ids)) != 4
        or generated_correct not in option_ids
        or accepted_answers
        or code_language is not None
        or code_requirements
    ):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The question generator returned invalid choices.")
    if question_type == "short_answer" and (
        generated_options or generated_correct is not None or accepted_answers or code_language is not None or code_requirements
    ):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The question generator returned invalid short-answer choices.")
    if question_type == "cloze" and (
        generated_options
        or generated_correct is not None
        or not accepted_answers
        or "_____" not in str(result.data["question"])
        or code_language is not None
        or code_requirements
    ):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The question generator returned invalid cloze content.")
    if question_type == "code" and (
        generated_options
        or generated_correct is not None
        or accepted_answers
        or str(code_language).lower() not in {"python", "javascript", "typescript", "java", "sql", "pseudocode"}
        or not code_requirements
    ):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The question generator returned invalid code content.")

    question = Question(
        node_id=node.id,
        course_id=node.course_id,
        question_type=generated_type,
        question_text=result.data["question"],
        options=generated_options,
        correct_option_id=generated_correct,
        accepted_answers=accepted_answers,
        code_language=str(code_language).lower() if code_language is not None else None,
        code_requirements=code_requirements,
        rubric=result.data["rubric"],
        difficulty=int(result.data["difficulty"]),
        source_chunk_ids=[c.id for c in chunks],
        prompt_version=f"{result.prompt_id}/{result.prompt_version}",
    )
    session.add(question)
    await session.flush()

    attempt = Attempt(
        user_id=user.id,
        node_id=node.id,
        course_id=node.course_id,
        question_id=question.id,
        status="issued",
        idempotency_key=idempotency_key,
    )
    session.add(attempt)
    try:
        await session.commit()
    except IntegrityError:
        # Two requests with the same Idempotency-Key raced past the SELECT
        # above and both tried to insert. The constraint is doing its job; the
        # loser should get the winner's attempt, which is what the caller asked
        # for. Surfacing a 500 here broke the documented idempotency contract
        # for the one case idempotency exists to cover.
        await session.rollback()
        settled = await session.scalar(
            select(Attempt).where(Attempt.user_id == user.id, Attempt.idempotency_key == idempotency_key)
        )
        if settled is None:
            raise
        question = await session.get(Question, settled.question_id)
        return await _project_drill(session, settled, question, node)

    await session.refresh(attempt)

    return await _project_drill(session, attempt, question, node)


async def _project_drill(
    session: AsyncSession, attempt: Attempt, question: Question | None, node: SkillNode
) -> DrillOut:
    if question is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Attempt has no question.")

    chunks = (
        list(await session.scalars(select(Chunk).where(Chunk.id.in_(question.source_chunk_ids))))
        if question.source_chunk_ids
        else []
    )
    return DrillOut(
        attempt_id=attempt.id,
        node_id=node.id,
        node_title=node.title,
        question=question.question_text,
        question_type=question.question_type,
        options=[QuestionOption.model_validate(option) for option in (question.options or [])],
        code_language=question.code_language,
        difficulty=question.difficulty,
        sources=[
            SourceRef(document_id=c.document_id, section_path=c.section_path, page_start=c.page_start)
            for c in chunks
        ],
    )


def _render_rubric(rubric: list[dict]) -> str:
    return "\n".join(f"{point['id']}: {point['point']} (weight {point['weight']})" for point in rubric)


def _normalise_answer(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _grade_cloze(question: Question, answer: str) -> dict[str, object]:
    selected = _normalise_answer(answer)
    accepted = {_normalise_answer(str(item)) for item in (question.accepted_answers or [])}
    hit = bool(selected) and selected in accepted
    point_ids = [str(point["id"]) for point in (question.rubric or [])]
    return {
        "score": 1.0 if hit else 0.0,
        "verdict": "correct" if hit else "incorrect",
        "feedback": (
            "Correct — the blank is filled with the expected concept."
            if hit
            else "That does not match the source-grounded answer for the blank."
        ),
        "points_hit": point_ids if hit else [],
        "points_missed": [] if hit else point_ids,
    }


def _grade_code(question: Question, answer: str) -> dict[str, object]:
    """Grade code without executing learner input.

    This is intentionally a static requirement check. It cannot prove runtime
    correctness, but it cannot run imports, filesystem access, network calls, or
    malicious code either. A future sandbox can replace this scorer behind the
    same question contract.
    """
    source = _normalise_answer(answer)
    requirements = [str(item) for item in (question.code_requirements or [])]
    hit: list[str] = []
    missed: list[str] = []
    for requirement in requirements:
        wanted = _normalise_answer(requirement)
        words = wanted.split()
        if words and all(word in source.split() for word in words):
            hit.append(requirement)
        else:
            missed.append(requirement)

    score = round(len(hit) / max(len(requirements), 1), 3)
    verdict = "correct" if score >= 0.85 else ("partial" if score > 0 else "incorrect")
    if not missed:
        feedback = "The snippet contains all required concepts. Runtime behavior was not executed."
    else:
        feedback = f"Static review found the required concepts missing: {', '.join(missed)}. Runtime behavior was not executed."
    return {
        "score": score,
        "verdict": verdict,
        "feedback": feedback,
        "points_hit": hit,
        "points_missed": missed,
    }


def _grade_mcq(question: Question, answer: str) -> dict[str, object]:
    """Grade a selected option without spending an LLM call.

    The option id is the wire answer, not the option's display text. Comparing
    ids avoids whitespace, casing, and duplicate-label ambiguity while keeping
    the correct answer out of the drill response.
    """
    selected = answer.strip().lower()
    correct = (question.correct_option_id or "").strip().lower()
    point_ids = [str(point["id"]) for point in (question.rubric or [])]
    hit = selected == correct and bool(correct)
    if hit:
        return {
            "score": 1.0,
            "verdict": "correct",
            "feedback": "Correct. You selected the option that matches the skill's key idea.",
            "points_hit": point_ids,
            "points_missed": [],
        }

    selected_text = next(
        (str(option.get("text", "")) for option in (question.options or []) if str(option.get("id", "")).lower() == selected),
        "That option",
    )
    correct_text = next(
        (str(option.get("text", "")) for option in (question.options or []) if str(option.get("id", "")).lower() == correct),
        "the correct option",
    )
    return {
        "score": 0.0,
        "verdict": "incorrect",
        "feedback": f"{selected_text} is not the best answer. The correct choice is: {correct_text}",
        "points_hit": [],
        "points_missed": point_ids,
    }


# @spec PROG-EXP-001, PROG-EXP-002, PROG-STATE-007
async def grade_attempt(
    session: AsyncSession, attempt_id: uuid.UUID, answer: str, user: User
) -> GradeResult:
    # Lock the row for the whole transaction. Without this, two concurrent
    # grades of one attempt -- a double-click, or a client that retries
    # aggressively -- both read status "issued", both grade, and both run
    # `progress.exp += ...` as a read-modify-write in separate transactions.
    # The idempotency guarantee held only for SEQUENTIAL retries.
    attempt = await session.scalar(select(Attempt).where(Attempt.id == attempt_id).with_for_update())
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found.")

    node = await _load_node(session, attempt.node_id, user.id)
    progress = await session.get(NodeProgress, (user.id, node.id))

    # Already graded: return the stored result verbatim. Retrying a request that
    # timed out client-side must never award EXP twice.
    if attempt.status == "graded":
        return await _project_grade(session, attempt, node, progress, user, level_before=progress.level, unlocked=[])

    question = await session.get(Question, attempt.question_id)
    if question is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Attempt has no question.")

    if question.question_type == "mcq":
        result_data = _grade_mcq(question, answer)
        grade_llm_call_id = None
        grade_prompt_version = "deterministic/mcq-v1"
    elif question.question_type == "cloze":
        result_data = _grade_cloze(question, answer)
        grade_llm_call_id = None
        grade_prompt_version = "deterministic/cloze-v1"
    elif question.question_type == "code":
        result_data = _grade_code(question, answer)
        grade_llm_call_id = None
        grade_prompt_version = "static/code-v1"
    else:
        chunks = (
            list(await session.scalars(select(Chunk).where(Chunk.id.in_(question.source_chunk_ids))))
            if question.source_chunk_ids
            else []
        )
        client = recording_llm_client(node.course_id)
        result = await client.structured(
            LLMRole.GRADE,
            {
                "question": question.question_text,
                "rubric": _render_rubric(question.rubric),
                "context": _render_context(chunks),
                "answer": answer,
            },
            course_id=str(node.course_id),
        )
        result_data = result.data
        grade_llm_call_id = result.llm_call_id
        grade_prompt_version = f"{result.prompt_id}/{result.prompt_version}"

    score = float(result_data["score"])
    now = datetime.now(timezone.utc)

    before_state = review_state_of(progress)
    level_before = progress.level if progress else 0
    was_overdue = overdue_days(before_state, now)
    # `reps == 0` alone is farmable: a failed review resets reps to 0 (see
    # app/domain/srs.py), so alternating a good answer with a blank one pays the
    # +50 first-pass bonus on every cycle, without limit. The bonus is for the
    # first time you ever demonstrated this skill, so it must key off something
    # monotone -- a node that has ever been reviewed has a last_reviewed_at.
    first_pass = (
        score >= 0.5
        and before_state.reps == 0
        and before_state.lapses == 0
        and before_state.last_reviewed_at is None
    )

    exp_gained = award_for_attempt(
        score=score,
        difficulty=question.difficulty,
        overdue_days=was_overdue,
        interval_days=before_state.interval_days,
        is_first_pass=first_pass,
    )

    after_state = schedule(before_state, score, now)

    progress.exp += exp_gained
    progress.level = node_level_for_exp(progress.exp)
    progress.mastery = after_state.mastery
    progress.ease = after_state.ease
    progress.interval_days = after_state.interval_days
    progress.reps = after_state.reps
    progress.lapses = after_state.lapses
    progress.last_reviewed_at = after_state.last_reviewed_at
    progress.due_at = after_state.due_at

    attempt.answer = answer
    attempt.score = score
    attempt.verdict = str(result_data["verdict"])
    attempt.feedback = str(result_data["feedback"])
    attempt.points_hit = list(result_data.get("points_hit") or [])
    attempt.points_missed = list(result_data.get("points_missed") or [])
    attempt.exp_awarded = exp_gained
    attempt.rescue_bonus_applied = was_overdue > 0
    attempt.status = "graded"
    attempt.graded_at = now
    attempt.prompt_version = grade_prompt_version
    # The column `models/attempt.py` has declared with a foreign key since day
    # one and nothing has ever written, which made every grade-to-cost join
    # return empty. The ledger commits on its own short-lived session (see
    # `repositories/llm_calls`), so the row is already durable here and the FK is
    # satisfied even though this attempt's transaction has not committed yet.
    # It stays nullable and is assigned unconditionally: a swallowed ledger write
    # yields None, which is the honest value, not a failed grade.
    attempt.grade_llm_call_id = grade_llm_call_id

    account_level_before = account_level_for_exp(user.total_exp)
    user.total_exp += exp_gained
    account_level_after = account_level_for_exp(user.total_exp)

    unlocked = await _newly_unlocked(session, node, user.id, before_state.mastery, after_state.mastery, now)

    await session.commit()
    await session.refresh(progress)
    await session.refresh(user)

    return await _project_grade(
        session,
        attempt,
        node,
        progress,
        user,
        level_before,
        unlocked,
        account_level_before=account_level_before,
        account_level_after=account_level_after,
    )


async def _drillable_dependents(
    session: AsyncSession,
    node_id: uuid.UUID,
    assessable: Mapping[uuid.UUID, bool],
) -> list[uuid.UUID]:
    """Dependents a learner could actually be sent to, seeing *through* containers.

    The mirror of `gating_masteries`, which walks up through non-assessable
    nodes; this walks down through them. Without it, mastering the last
    prerequisite of a chapter reports the *chapter* as newly unlocked -- a node
    with nothing to drill -- and never names the section that genuinely opened
    up. Not a lock-out (the graph refetch is correct either way), but the unlock
    is the one moment the product promises a reward, and it pointed at a heading.
    """
    resolved: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    frontier = [node_id]

    while frontier:
        current = frontier.pop()
        targets = await session.scalars(select(SkillEdge.target_id).where(SkillEdge.prereq_id == current))
        for target in targets:
            if target in seen:
                pass
            else:
                seen.add(target)
                if assessable.get(target, True):
                    resolved.append(target)
                else:
                    frontier.append(target)

    return resolved


async def _newly_unlocked(
    session: AsyncSession,
    node: SkillNode,
    user_id: uuid.UUID,
    mastery_before: float,
    mastery_after: float,
    now: datetime,
) -> list[uuid.UUID]:
    """Dependents that become reachable because this node crossed the threshold.

    Only computed when the crossing actually happened, so an ordinary review of
    an already-mastered node does not re-trigger the unlock animation.
    """
    crossed = mastery_before < PREREQ_MASTERY_THRESHOLD <= mastery_after
    if not crossed:
        return []

    prereqs, mastery, assessable = await _course_gating(session, node.course_id, user_id)

    dependents = await _drillable_dependents(session, node.id, assessable)
    if not dependents:
        return []

    # Substitute by NODE ID, not by value. Matching on `abs(m - mastery_before)`
    # hit any sibling prerequisite that happened to hold the same mastery --
    # which is the normal case when two nodes have been drilled the same number
    # of times against a deterministic grader. That reported a node as unlocked
    # while a sibling was still short, so the UI played the unlock and the very
    # next graph fetch showed it locked again.
    mastery[node.id] = mastery_after

    unlocked: list[uuid.UUID] = []
    for dependent_id in dependents:
        masteries = gating_masteries(dependent_id, prereqs, mastery, assessable)
        if masteries and all(m >= PREREQ_MASTERY_THRESHOLD for m in masteries):
            unlocked.append(dependent_id)

    return unlocked


async def _project_grade(
    session: AsyncSession,
    attempt: Attempt,
    node: SkillNode,
    progress: NodeProgress,
    user: User,
    level_before: int,
    unlocked: list[uuid.UUID],
    account_level_before: int | None = None,
    account_level_after: int | None = None,
) -> GradeResult:
    now = datetime.now(timezone.utc)
    state = review_state_of(progress)
    derived = derive_state(
        state, progress.level, await _prerequisite_masteries(session, node, user.id), now
    )

    resolved_account_level = account_level_after if account_level_after is not None else account_level_for_exp(user.total_exp)
    resolved_account_before = (
        account_level_before if account_level_before is not None else resolved_account_level
    )

    return GradeResult(
        attempt_id=attempt.id,
        node_id=node.id,
        score=attempt.score or 0.0,
        verdict=attempt.verdict or "incorrect",
        feedback=attempt.feedback or "",
        points_hit=list(attempt.points_hit or []),
        points_missed=list(attempt.points_missed or []),
        exp_awarded=attempt.exp_awarded,
        rescue_bonus_applied=attempt.rescue_bonus_applied,
        level_before=level_before,
        level_after=progress.level,
        level_up=progress.level > level_before,
        account_level_before=resolved_account_before,
        account_level_after=resolved_account_level,
        account_level_up=resolved_account_level > resolved_account_before,
        user_total_exp=user.total_exp,
        progress=NodeProgressOut(
            state=derived.value,
            exp=progress.exp,
            level=progress.level,
            mastery=round(state.mastery, 4),
            proficiency=round(proficiency(state, now), 4),
            due_at=state.due_at,
            overdue_days=round(overdue_days(state, now), 3),
        ),
        unlocked_node_ids=unlocked,
    )


# Keep the registry import meaningful for readers checking which models serve
# these roles without opening another file.
QUESTION_MODEL = ROLES[LLMRole.QUESTION_GEN]
GRADE_MODEL = ROLES[LLMRole.GRADE]
