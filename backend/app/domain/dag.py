"""Skill-graph structure: cycle rejection, topological layering, transitive reduction.

Pure. No database, no network, no framework imports. This module is the single
choke point through which every edge must pass before it reaches `skill_edges` --
the LLM is asked not to produce cycles, but asking is not enforcing.

House style note: this file contains no `continue` statements (see CLAUDE.md).
Every loop body branches explicitly so each decision is visible where it is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "CandidateEdge",
    "RejectedEdge",
    "CycleError",
    "build_acyclic_edges",
    "topological_depths",
    "transitive_reduction",
]


@dataclass(frozen=True, slots=True)
class CandidateEdge:
    """A prerequisite relationship proposed by the extractor.

    `prereq` must be learned before `target` -- read the pair as an arrow
    prereq -> target.
    """

    prereq: str
    target: str
    confidence: float = 1.0
    support: int = 1
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class RejectedEdge:
    """An edge that did not make it into the graph, and why.

    Persisted to `skill_edge_rejections`. The `cycle_path` is the actual chain
    that would have been closed, which is the most useful debugging artifact the
    extraction pipeline produces.
    """

    prereq: str
    target: str
    reason: str  # self_loop | duplicate | unknown_node | low_confidence | cycle
    confidence: float = 0.0
    cycle_path: tuple[str, ...] = field(default_factory=tuple)
    # Carried over from the candidate. A rejection that drops the claim it
    # rejected leaves a reviewer looking at two slugs and a reason code, with no
    # way to judge whether the compiler or the extractor was wrong.
    support: int = 1
    rationale: str = ""


class CycleError(ValueError):
    """Raised when a graph asserted to be acyclic is not."""

    def __init__(self, unresolved: list[str]) -> None:
        super().__init__(f"graph contains a cycle involving: {sorted(unresolved)}")
        self.unresolved = sorted(unresolved)


def _find_path(adjacency: dict[str, set[str]], start: str, goal: str) -> tuple[str, ...]:
    """Return a path start -> ... -> goal, or an empty tuple if none exists.

    Iterative depth-first search with an explicit stack. Successors are visited
    in sorted order so the reported path is deterministic, which matters because
    it gets written to the database and compared in tests.
    """
    if start == goal:
        return (start,)

    stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
    visited: set[str] = set()
    found: tuple[str, ...] = ()

    while stack and not found:
        current, path = stack.pop()
        if current == goal:
            found = path
        elif current in visited:
            pass  # already expanded; fall through to the next stack entry
        else:
            visited.add(current)
            for successor in sorted(adjacency.get(current, ()), reverse=True):
                stack.append((successor, path + (successor,)))

    return found


# @spec PROG-DAG-002, PROG-DAG-003, PROG-DAG-006, PROG-DAG-007
def build_acyclic_edges(
    node_slugs: set[str],
    candidates: list[CandidateEdge],
    min_confidence: float = 0.35,
) -> tuple[list[CandidateEdge], list[RejectedEdge]]:
    """Admit edges greedily in descending confidence, skipping any that close a cycle.

    Post-condition: the accepted set is a DAG over `node_slugs`. This is
    guaranteed by construction rather than checked afterwards -- an edge is only
    added once we know its target cannot already reach its source.

    Greedy-by-confidence makes the failure mode sensible. When the extractor
    claims both `limits -> derivatives` (0.95) and `derivatives -> limits` (0.41),
    the confident direction survives and the contradiction is recorded with the
    path it would have closed.

    Determinism: ties break on (-confidence, -support, prereq, target), so
    re-ingesting an unchanged document produces a byte-identical graph.
    """
    adjacency: dict[str, set[str]] = {slug: set() for slug in node_slugs}
    accepted: list[CandidateEdge] = []
    rejected: list[RejectedEdge] = []
    seen: set[tuple[str, str]] = set()

    ordered = sorted(candidates, key=lambda e: (-e.confidence, -e.support, e.prereq, e.target))

    for edge in ordered:
        pair = (edge.prereq, edge.target)

        if edge.prereq == edge.target:
            rejected.append(
                RejectedEdge(
                    edge.prereq, edge.target, "self_loop", edge.confidence,
                    support=edge.support, rationale=edge.rationale,
                )
            )
        elif edge.prereq not in adjacency or edge.target not in adjacency:
            rejected.append(
                RejectedEdge(
                    edge.prereq, edge.target, "unknown_node", edge.confidence,
                    support=edge.support, rationale=edge.rationale,
                )
            )
        elif pair in seen:
            rejected.append(
                RejectedEdge(
                    edge.prereq, edge.target, "duplicate", edge.confidence,
                    support=edge.support, rationale=edge.rationale,
                )
            )
        elif edge.confidence < min_confidence:
            rejected.append(
                RejectedEdge(
                    edge.prereq, edge.target, "low_confidence", edge.confidence,
                    support=edge.support, rationale=edge.rationale,
                )
            )
        else:
            # If target already reaches prereq, adding prereq -> target closes a loop.
            back_path = _find_path(adjacency, edge.target, edge.prereq)
            if back_path:
                rejected.append(
                    RejectedEdge(
                        edge.prereq, edge.target, "cycle", edge.confidence, back_path,
                        support=edge.support, rationale=edge.rationale,
                    )
                )
            else:
                adjacency[edge.prereq].add(edge.target)
                seen.add(pair)
                accepted.append(edge)

    return accepted, rejected


# @spec PROG-DAG-004
def topological_depths(node_slugs: set[str], edges: list[CandidateEdge]) -> dict[str, int]:
    """Kahn's algorithm, layered. Returns the depth of every slug.

    Serves two purposes: it is the post-condition assertion that
    `build_acyclic_edges` did its job (it raises on a cyclic input), and its
    output populates `skill_nodes.depth`, which becomes the dagre rank so the
    rendered tree layers by genuine prerequisite depth rather than by whatever
    order the layout engine happened to walk.
    """
    indegree: dict[str, int] = {slug: 0 for slug in node_slugs}
    outgoing: dict[str, list[str]] = {slug: [] for slug in node_slugs}

    for edge in edges:
        if edge.prereq in outgoing and edge.target in indegree:
            outgoing[edge.prereq].append(edge.target)
            indegree[edge.target] += 1
        else:
            raise CycleError([edge.prereq, edge.target])

    depth: dict[str, int] = {slug: 0 for slug in node_slugs if indegree[slug] == 0}
    frontier = sorted(depth)
    settled: list[str] = []

    while frontier:
        next_frontier: list[str] = []
        for slug in frontier:
            settled.append(slug)
            for child in outgoing[slug]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    depth[child] = depth[slug] + 1
                    next_frontier.append(child)
        frontier = sorted(next_frontier)

    if len(settled) != len(node_slugs):
        raise CycleError(list(set(node_slugs) - set(settled)))

    return depth


# @spec PROG-DAG-005
def transitive_reduction(node_slugs: set[str], edges: list[CandidateEdge]) -> list[CandidateEdge]:
    """Drop `u -> v` when a longer path `u -> ... -> v` already exists.

    Display concern only: the full edge set stays in Postgres, and this reduced
    set is what the API returns for rendering. On a real textbook roughly 40% of
    extracted edges are transitively implied, and drawing them turns a legible
    tree into a hairball. Per line of code this is the single biggest win for
    perceived graph quality.

    Assumes `edges` is acyclic (i.e. already through `build_acyclic_edges`).
    """
    adjacency: dict[str, set[str]] = {slug: set() for slug in node_slugs}
    for edge in edges:
        if edge.prereq in adjacency:
            adjacency[edge.prereq].add(edge.target)

    kept: list[CandidateEdge] = []
    for edge in sorted(edges, key=lambda e: (e.prereq, e.target)):
        # Temporarily remove the direct edge and ask whether the target is still
        # reachable. If it is, this edge adds no information.
        adjacency[edge.prereq].discard(edge.target)
        implied = bool(_find_path(adjacency, edge.prereq, edge.target))
        if implied:
            pass  # redundant: leave it out and leave the direct edge removed
        else:
            adjacency[edge.prereq].add(edge.target)
            kept.append(edge)

    return kept
