"""A dependency-ordered walk through a course.

`domain.dag.topological_depths` already computes this order on every ingest, and
until now it was used to set `skill_nodes.depth` for the layout engine and then
thrown away. A tech tree that knows which node comes first and never says so is
the shortest gap between what this product has and what it claims.

## Two rules the order has to obey

**Containers are not steps.** A structural node cannot be drilled, so putting one
in a walk sends the learner to a page with nothing on it -- the same defect
`gating_masteries` fixes for locking and `_drillable_dependents` fixes for
unlocks. The transparency rule is copied from those: a container is *seen
through*, contributing its own prerequisites to whatever depends on it, so
dropping it from the walk loses no ordering. A chapter heading between two
sections still keeps the second after the first.

**Depth comes from the contracted graph, not from `skill_nodes.depth`.** The
stored depth counts containers as layers, so two sections separated only by a
chapter heading get depths 2 and 4, and the walk reports a gap that does not
exist for a learner.

## What "adapt to the learner" means here

The walk itself does not reorder. A prerequisite order is a property of the
material, and a path that reshuffles between visits is one nobody can hold in
their head -- the learner loses the map they were building. What adapts is the
*cursor*: every step carries its own state and `done`, and `next_node_id` is the
first step not yet cleared. Progress moves the pointer; it does not rewrite the
route.

That also makes the pointer safe by construction. Steps are in topological
order, so when every earlier step is done, every prerequisite of the first
un-done step is done too -- `next_node_id` can never name a locked node.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dag import CandidateEdge, topological_depths
from app.domain.exp import node_level_for_exp
from app.domain.states import PREREQ_MASTERY_THRESHOLD, derive_state, gating_masteries
from app.models import Course, NodeProgress, SkillEdge, SkillNode
from app.schemas.explore import CoursePath, PathStep
from app.services.graph_read import ensure_progress_rows, review_state_of


def contracted_prereqs(
    prereqs: dict[uuid.UUID, list[uuid.UUID]],
    assessable: dict[uuid.UUID, bool],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Prerequisites among drillable nodes only, seeing through containers.

    The id-returning twin of `domain.states.gating_masteries`, which returns
    their masteries. `seen` guards the walk for the same reason it does there:
    the graph is a DAG by construction, but this reads rows from a database and
    a corrupt one should degrade rather than hang the request.
    """
    resolved: dict[uuid.UUID, set[uuid.UUID]] = {}

    for node_id, drillable in assessable.items():
        if not drillable:
            pass
        else:
            found: set[uuid.UUID] = set()
            seen: set[uuid.UUID] = set()
            frontier = list(prereqs.get(node_id, ()))
            while frontier:
                current = frontier.pop()
                if current in seen:
                    pass
                elif assessable.get(current, True):
                    seen.add(current)
                    found.add(current)
                else:
                    seen.add(current)
                    frontier.extend(prereqs.get(current, ()))
            # A node is never its own prerequisite. Unreachable on a DAG, but a
            # corrupt row that made one would become a self-edge, and
            # `topological_depths` cannot settle a node whose indegree includes
            # itself -- it would report the whole course as a cycle.
            found.discard(node_id)
            resolved[node_id] = found

    return resolved


async def build_path(session: AsyncSession, course: Course, user_id: uuid.UUID) -> CoursePath:
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    edges = list(await session.scalars(select(SkillEdge).where(SkillEdge.course_id == course.id)))
    if not nodes:
        return CoursePath(course_id=course.id, steps=[], next_node_id=None, completed=0, total=0)

    await ensure_progress_rows(session, user_id, [node.id for node in nodes])
    progress_rows = {
        row.node_id: row
        for row in await session.scalars(
            select(NodeProgress).where(
                NodeProgress.user_id == user_id,
                NodeProgress.node_id.in_([node.id for node in nodes]),
            )
        )
    }

    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {node.id: [] for node in nodes}
    for edge in edges:
        if edge.target_id in prereqs:
            prereqs[edge.target_id].append(edge.prereq_id)

    assessable = {node.id: node.assessable for node in nodes}
    walkable = [node for node in nodes if node.assessable]
    slug_of = {node.id: node.slug for node in walkable}
    resolved = contracted_prereqs(prereqs, assessable)

    slugs = set(slug_of.values())
    candidates = [
        CandidateEdge(prereq=slug_of[prereq_id], target=slug_of[node_id])
        for node_id, found in resolved.items()
        for prereq_id in sorted(found, key=lambda pid: slug_of.get(pid, ""))
        if prereq_id in slug_of and node_id in slug_of
    ]
    depths = topological_depths(slugs, candidates)

    now = datetime.now(timezone.utc)
    states = {node.id: review_state_of(progress_rows.get(node.id)) for node in nodes}
    mastery_by_id = {node_id: state.mastery for node_id, state in states.items()}

    ordered = sorted(walkable, key=lambda node: (depths[node.slug], node.difficulty, node.title))

    steps: list[PathStep] = []
    for index, node in enumerate(ordered):
        state = states[node.id]
        row = progress_rows.get(node.id)
        level = row.level if row else node_level_for_exp(0)
        derived = derive_state(state, level, gating_masteries(node.id, prereqs, mastery_by_id, assessable), now)
        steps.append(
            PathStep(
                order=index,
                node_id=node.id,
                slug=node.slug,
                title=node.title,
                summary=node.summary,
                depth=depths[node.slug],
                difficulty=node.difficulty,
                state=derived.value,
                mastery=round(state.mastery, 4),
                done=state.mastery >= PREREQ_MASTERY_THRESHOLD,
            )
        )

    upcoming = [step for step in steps if not step.done]
    return CoursePath(
        course_id=course.id,
        steps=steps,
        next_node_id=upcoming[0].node_id if upcoming else None,
        completed=len(steps) - len(upcoming),
        total=len(steps),
    )
