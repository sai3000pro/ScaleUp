"""A proposal the system cannot trust never costs the learner their tree.

The floor is the whole argument for goal-first construction: a model that returns
nonsense, a provider that is down, and a budget that is spent are all the same
event from the learner's side, and none of them may end with an empty course.

Each case here breaks the proposal in a different way and asserts the same two
things — a playable tree came back, and it is labelled as assembled rather than
proposed, because the label is what keeps publishing-immediately honest.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.llm.base import LLMRole, ProviderError, StructuredResult, Usage
from app.models import CurriculumVersion, SkillEdge, SkillNode
from app.repositories.llm_calls import LlmCall
from app.services import curriculum_plan_service

GOAL = "I want to learn how to play the cello"


def _fake_result(data: dict) -> StructuredResult:
    return StructuredResult(
        data=data,
        raw_text="<test>",
        model="test",
        usage=Usage(input_tokens=0, output_tokens=0),
        prompt_id="curriculum_plan",
        prompt_version="v1",
        prompt_sha256="0" * 64,
        provider="test",
        request_fingerprint="0" * 64,
    )


class _Client:
    """Stands in for the recording gateway client, returning what the test wants."""

    def __init__(self, behaviour) -> None:
        self._behaviour = behaviour

    async def structured(self, role: LLMRole, variables, *, course_id=None) -> StructuredResult:
        return self._behaviour(role, variables)


def _install(monkeypatch, behaviour) -> None:
    monkeypatch.setattr(
        curriculum_plan_service, "recording_llm_client", lambda course_id=None: _Client(behaviour)
    )


def _assert_playable_and_assembled(payload: dict) -> None:
    assert payload["node_count"] >= 4, "a rejected plan must still leave a real tree"
    assert payload["edge_count"] > 0, "a tree with no edges is a list"
    with sync_session() as session:
        version = session.scalar(
            select(CurriculumVersion).where(
                CurriculumVersion.course_id == payload["id"],
                CurriculumVersion.status == "published",
            )
        )
        nodes = session.scalars(select(SkillNode).where(SkillNode.course_id == payload["id"])).all()
        edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == payload["id"])).all()
    assert version is not None
    assert version.compiler_version == curriculum_plan_service.ASSEMBLED, (
        "a fallback tree must not be labelled as a model proposal"
    )
    assert nodes and edges


# @spec CURR-GOAL-011
async def test_a_plan_naming_a_skill_the_catalogue_lacks_falls_back(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch,
        lambda role, variables: _fake_result(
            {
                "instrument": "cello",
                "instrument_title": "Cello",
                "concepts": [
                    {"from": "not-a-real-skill", "slug": f"cello-{index}"} for index in range(6)
                ],
                "edges": [],
            }
        ),
    )

    response = await authed_client.post("/api/courses/from-goal", json={"goal": GOAL})

    assert response.status_code == 201, response.text
    _assert_playable_and_assembled(response.json())


# @spec CURR-GOAL-011
async def test_a_plan_too_small_to_be_a_curriculum_falls_back(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch,
        lambda role, variables: _fake_result(
            {
                "instrument": "cello",
                "instrument_title": "Cello",
                "concepts": [{"from": "steady-pulse", "slug": "cello-pulse"}],
                "edges": [],
            }
        ),
    )

    response = await authed_client.post("/api/courses/from-goal", json={"goal": GOAL})

    assert response.status_code == 201, response.text
    _assert_playable_and_assembled(response.json())


# @spec CURR-GOAL-011
async def test_a_provider_outage_still_returns_a_tree(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider is an upgrade, never a dependency."""

    def explode(role, variables):
        raise ProviderError("the provider is unreachable")

    _install(monkeypatch, explode)

    response = await authed_client.post("/api/courses/from-goal", json={"goal": GOAL})

    assert response.status_code == 201, response.text
    _assert_playable_and_assembled(response.json())


# @spec CURR-GOAL-011, CURR-GOAL-012
async def test_a_valid_proposal_is_taken_and_labelled_as_proposed(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the rule: a plan that validates is actually used."""
    _install(
        monkeypatch,
        lambda role, variables: _fake_result(
            {
                "instrument": "cello",
                "instrument_title": "Cello",
                "concepts": [
                    {"from": "instrument-orientation", "slug": "cello-hold", "title": "Holding the Cello"},
                    {"from": "steady-pulse", "slug": "cello-pulse"},
                    {"from": "sustained-tone", "slug": "cello-bow"},
                    {
                        "slug": "cello-thumb-position",
                        "title": "Thumb Position",
                        "summary": "Play above the neck with the thumb stopping the string.",
                        "difficulty": 5,
                    },
                ],
                "edges": [
                    {"prereq": "cello-hold", "target": "cello-pulse", "confidence": 0.9, "rationale": "Hold first."},
                    {"prereq": "cello-bow", "target": "cello-thumb-position", "confidence": 0.8, "rationale": "Tone first."},
                ],
            }
        ),
    )

    response = await authed_client.post("/api/courses/from-goal", json={"goal": GOAL})

    assert response.status_code == 201, response.text
    payload = response.json()
    with sync_session() as session:
        version = session.scalar(
            select(CurriculumVersion).where(
                CurriculumVersion.course_id == payload["id"], CurriculumVersion.status == "published"
            )
        )
        slugs = {
            node.slug
            for node in session.scalars(select(SkillNode).where(SkillNode.course_id == payload["id"]))
        }
    assert version is not None
    assert version.compiler_version == curriculum_plan_service.PROPOSED
    assert "cello-thumb-position" in slugs, "an instrument-specific concept should survive"
    assert "cello-hold" in slugs


# @spec CURR-GOAL-018
async def test_the_plan_call_is_recorded_against_the_course_it_built(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A goal-built tree's spend has to land on the course the learner got.

    The ledger writes from its own session, so the course row has to be committed
    before the model is asked -- `llm_calls.course_id` is a foreign key, and an
    uncommitted course is one that session cannot see. When that ordering was
    wrong the row was refused and every goal-built tree spent money invisibly,
    which no test noticed because the deterministic provider costs nothing.
    """
    # The real RecordingLLMClient, wrapping a stub provider. Replacing the
    # recorder itself -- which every other test here does, because they are about
    # what the planner does with a reply -- would skip the ledger entirely and
    # make this assertion impossible to fail.
    from app.services import llm_gateway

    class _Inner:
        provider = "test"

        def model_for(self, role: LLMRole) -> str:
            return "test"

        async def structured(self, role, variables, *, course_id=None) -> StructuredResult:
            return _fake_result({"instrument": "cello", "concepts": [], "edges": []})

    monkeypatch.setattr(llm_gateway, "get_llm_client", _Inner)

    response = await authed_client.post("/api/courses/from-goal", json={"goal": GOAL})
    assert response.status_code == 201, response.text
    course_id = response.json()["id"]

    with sync_session() as session:
        rows = session.scalars(
            select(LlmCall).where(LlmCall.course_id == uuid.UUID(course_id))
        ).all()

    assert rows, "the plan call left no ledger row against its own course"
    assert {row.role for row in rows} == {"curriculum_plan"}
