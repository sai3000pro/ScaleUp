from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.llm.base import LLMRole
from app.llm.fake_provider import FakeLLMClient
from app.services import campaign_service


class OutcomeSession:
    def __init__(self, proposal: SimpleNamespace | None, nodes: list[SimpleNamespace]) -> None:
        self.proposal = proposal
        self.nodes = nodes

    async def scalar(self, _statement: object) -> SimpleNamespace | None:
        return self.proposal

    async def scalars(self, _statement: object) -> list[SimpleNamespace]:
        return self.nodes


@pytest.mark.asyncio
async def test_fake_outcome_evaluator_is_structured_and_deterministic() -> None:
    result = await FakeLLMClient().structured(
        LLMRole.CAMPAIGN_OUTCOME_EVAL,
        {
            "outcome": "build a robot policy",
            "skills": (
                "- robot-foundations | Robot Foundations | Core concepts for robot systems.\n"
                "- policy-evaluation | Policy Evaluation | Evaluate a robot policy in simulation."
            ),
        },
    )

    assert result.provider == "fake"
    assert result.data["matched_skill_slugs"] == ["robot-foundations", "policy-evaluation"]
    assert result.data["missing_capabilities"] == ["build"]
    assert result.data["readiness"] == pytest.approx(2 / 3, rel=0.01)


@pytest.mark.asyncio
async def test_campaign_service_closes_model_output_over_actual_skill_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    course_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    proposal = SimpleNamespace(target_outcome="build a robot policy", proposal_version=1)
    nodes = [
        SimpleNamespace(
            id=first_id,
            slug="robot-foundations",
            title="Robot Foundations",
            summary="Core concepts for robot systems.",
            depth=0,
            assessable=True,
        ),
        SimpleNamespace(
            id=second_id,
            slug="policy-evaluation",
            title="Policy Evaluation",
            summary="Evaluate a robot policy in simulation.",
            depth=1,
            assessable=True,
        ),
    ]

    class FakeClient:
        provider = "fake"

        async def structured(self, _role: LLMRole, _variables: dict[str, str], *, course_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                data={
                    "matched_skill_slugs": ["policy-evaluation", "not-in-tree"],
                    "missing_capabilities": ["build"],
                    "readiness": 0.5,
                    "rationale": "The tree covers evaluation but not the act of building.",
                }
            )

    monkeypatch.setattr(campaign_service, "recording_llm_client", lambda _course_id: FakeClient())
    result = await campaign_service.evaluate_outcome(
        OutcomeSession(proposal, nodes),
        SimpleNamespace(id=course_id, owner_id=uuid4()),
    )

    assert result.mode == "deterministic"
    assert result.evaluated_skill_count == 2
    assert [(skill.id, skill.title) for skill in result.matched_skills] == [(second_id, "Policy Evaluation")]
    assert result.missing_capabilities == ["build"]
    assert result.readiness == 0.5
    assert result.side_quests[0].capability == "build"
    assert result.side_quests[0].source_query.startswith("build a robot policy; focus on build")
