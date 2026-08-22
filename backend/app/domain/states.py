"""Node visual state derivation.

Pure, and mirrored in frontend/lib/skill-tree/nodeState.ts so the UI can recolour
a node optimistically after a grade without waiting for the next fetch. The
server's value wins on reconcile.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Hashable, Mapping, Sequence

from app.domain.srs import ReviewState

__all__ = [
    "NodeState",
    "PREREQ_MASTERY_THRESHOLD",
    "MASTERED_MASTERY",
    "MASTERED_LEVEL",
    "derive_state",
    "overdue_days",
    "gating_masteries",
]

# A prerequisite counts as cleared at half mastery. Requiring full mastery to
# unlock anything downstream makes the tree feel like a wall; requiring nothing
# makes the prerequisite structure decorative.
PREREQ_MASTERY_THRESHOLD = 0.5
MASTERED_MASTERY = 0.85
MASTERED_LEVEL = 5


class NodeState(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    LEARNING = "learning"
    DECAYING = "decaying"
    MASTERED = "mastered"


# @spec PROG-STATE-002, PROG-STATE-005, PROG-DAG-008
def gating_masteries(
    node_id: Hashable,
    prereqs: Mapping[Hashable, Sequence[Hashable]],
    mastery: Mapping[Hashable, float],
    assessable: Mapping[Hashable, bool],
) -> list[float]:
    """The masteries that should gate `node_id`, seeing *through* structural nodes.

    A node with `assessable=False` can never be drilled, so no attempt is ever
    recorded against it and its mastery stays 0.0 for ever. Feeding that raw 0.0
    in as a prerequisite mastery locks every descendant permanently, with no
    in-app way out: the structural node is also excluded from the quest board,
    so nothing can ever unlock it. One such node quarantines its whole subtree.

    The fix is to treat a structural node as *transparent* rather than
    unfinished: it contributes the masteries of its OWN prerequisites instead of
    its own non-existent one. A structural node with no prerequisites is
    trivially cleared and contributes nothing, so a container chapter no longer
    blocks its sections -- while a container that genuinely sits behind real
    prerequisites still passes those through.

    Cycles cannot occur (the graph is a DAG by construction), but `seen` guards
    the recursion anyway: this runs on data from the database, and a corrupt row
    should degrade rather than hang the request.
    """
    resolved: list[float] = []
    seen: set[Hashable] = set()

    def walk(current: Hashable) -> None:
        for prereq in prereqs.get(current, ()):  # noqa: B007
            if prereq in seen:
                pass
            else:
                seen.add(prereq)
                if assessable.get(prereq, True):
                    resolved.append(mastery.get(prereq, 0.0))
                else:
                    walk(prereq)

    walk(node_id)
    return resolved


def overdue_days(state: ReviewState, now: datetime) -> float:
    if state.due_at is None or state.due_at >= now:
        return 0.0
    return (now - state.due_at).total_seconds() / 86400.0


# @spec PROG-STATE-001, PROG-STATE-003, PROG-STATE-004
def derive_state(
    state: ReviewState,
    level: int,
    prerequisite_masteries: list[float],
    now: datetime,
) -> NodeState:
    """First match wins.

    `decaying` is checked before `mastered` on purpose: a mastered node that has
    gone overdue should read as decaying. That urgency is the whole retention
    mechanic -- if mastery were permanent, the Daily Quest board would have
    nothing to say.

    `prerequisite_masteries` carries one entry per incoming edge; a prerequisite
    the user has never touched contributes 0.0.
    """
    blocked = any(mastery < PREREQ_MASTERY_THRESHOLD for mastery in prerequisite_masteries)

    if blocked:
        return NodeState.LOCKED
    if state.due_at is not None and state.due_at < now:
        return NodeState.DECAYING
    if level >= MASTERED_LEVEL and state.mastery >= MASTERED_MASTERY:
        return NodeState.MASTERED
    if state.reps > 0:
        return NodeState.LEARNING
    return NodeState.AVAILABLE
