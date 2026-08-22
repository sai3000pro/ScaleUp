"""Explore, search, ask.

A separate module from `courses.py` rather than three more handlers in it: these
are the read surface a learner uses to *navigate* a course, where `courses.py` is
the surface that creates and ingests one. They share the `/api/courses` prefix
because they are all scoped to a course, and ownership runs through
`course_service.get_owned`, which 404s rather than 403s so a course id is not an
enumeration oracle.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.explore import AskAnswer, AskRequest, CoursePath, SearchResults
from app.services import course_service, path_service, qa_service, search_service

router = APIRouter(prefix="/api/courses", tags=["explore"])


@router.get("/{course_id}/search", response_model=SearchResults)
async def search_course(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    q: str = Query(min_length=1, max_length=200, description="Free text. Matched against node titles and chunk meaning."),
    limit: int = Query(search_service.RESULT_LIMIT, ge=1, le=50),
) -> SearchResults:
    """Rank this course's skills against a query, by name and by meaning.

    Degrades rather than fails when the vector index is unreachable: title
    matching still answers, and `semantic: false` says the other half is missing.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await search_service.search(session, course, q, limit)


@router.post("/{course_id}/ask", response_model=AskAnswer)
async def ask_course(
    course_id: uuid.UUID,
    payload: AskRequest,
    user: CurrentUser,
    session: DbSession,
) -> AskAnswer:
    """Answer a question from this course's own material, citing the nodes it came from.

    Every citation names a passage the model was shown and quotes it verbatim;
    anything else is discarded before it reaches the response. `retrieved: 0`
    means nothing was found to ground an answer, and no model call was made.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await qa_service.ask(session, course, payload.question)


@router.get("/{course_id}/path", response_model=CoursePath)
async def course_path(course_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CoursePath:
    """The dependency-ordered walk: what to learn first, and what comes next.

    Containers are excluded as steps but still respected as ordering, and
    `next_node_id` follows the learner's progress without reordering the route.
    """
    course = await course_service.get_owned(session, course_id, user.id)
    return await path_service.build_path(session, course, user.id)
