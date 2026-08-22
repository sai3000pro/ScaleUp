from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.campaign_service import build_briefing


class FakeSession:
    def __init__(self, proposal: SimpleNamespace | None, nodes: list[SimpleNamespace], edges: list[SimpleNamespace]) -> None:
        self.proposal = proposal
        self.nodes = nodes
        self.edges = edges

    async def scalar(self, _statement: object) -> SimpleNamespace | None:
        return self.proposal

    async def scalars(self, _statement: object) -> list[SimpleNamespace]:
        return self.nodes

    async def execute(self, _statement: object) -> list[tuple[object, object]]:
        return [(edge.prereq_id, edge.target_id) for edge in self.edges]


@pytest.mark.asyncio
async def test_build_briefing_projects_playable_tree_and_outcome_coverage() -> None:
    course_id = uuid4()
    owner_id = uuid4()
    foundation_id = uuid4()
    application_id = uuid4()
    structural_id = uuid4()
    proposal = SimpleNamespace(
        goal="learn robotics",
        target_outcome="build a robot policy",
        proposal_version=3,
    )
    nodes = [
        SimpleNamespace(
            id=foundation_id,
            assessable=True,
            depth=0,
            title="Robot foundations",
            summary="Core concepts for robot systems.",
        ),
        SimpleNamespace(
            id=structural_id,
            assessable=False,
            depth=1,
            title="Applied robotics",
            summary="A structural grouping.",
        ),
        SimpleNamespace(
            id=application_id,
            assessable=True,
            depth=2,
            title="Policy evaluation",
            summary="Evaluate a robot policy in simulation.",
        ),
    ]
    edges = [
        SimpleNamespace(prereq_id=foundation_id, target_id=structural_id),
        SimpleNamespace(prereq_id=structural_id, target_id=application_id),
    ]

    briefing = await build_briefing(
        FakeSession(proposal, nodes, edges),
        SimpleNamespace(id=course_id, owner_id=owner_id),
    )

    assert briefing.course_id == course_id
    assert briefing.goal == "learn robotics"
    assert briefing.target_outcome == "build a robot policy"
    assert briefing.proposal_version == 3
    assert briefing.tree_shape.playable_skills == 2
    assert briefing.tree_shape.branches == 1
    assert briefing.tree_shape.prerequisite_links == 1
    assert briefing.tree_shape.depth == 3
    assert briefing.tree_shape.depth_counts == {"0": 1, "2": 1}
    assert [skill.title for skill in briefing.tree_shape.starting_skills] == ["Robot foundations"]
    assert briefing.outcome_coverage.terms == ["build", "robot", "policy"]
    assert briefing.outcome_coverage.matched_terms == ["robot", "policy"]
    assert briefing.outcome_coverage.missing_terms == ["build"]
    assert briefing.outcome_coverage.coverage == pytest.approx(0.6667)


@pytest.mark.asyncio
async def test_build_briefing_without_proposal_returns_empty_objective() -> None:
    course_id = uuid4()
    node_id = uuid4()

    briefing = await build_briefing(
        FakeSession(
            None,
            [
                SimpleNamespace(
                    id=node_id,
                    assessable=True,
                    depth=0,
                    title="Vectors",
                    summary="Magnitude and direction.",
                )
            ],
            [],
        ),
        SimpleNamespace(id=course_id, owner_id=uuid4()),
    )

    assert briefing.target_outcome == ""
    assert briefing.proposal_version is None
    assert briefing.outcome_coverage.terms == []
    assert briefing.outcome_coverage.coverage == 0.0
    assert briefing.outcome_coverage.signal == "No victory condition supplied."
