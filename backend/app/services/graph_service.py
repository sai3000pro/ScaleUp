"""Persisting a skill graph.

The single write path for `skill_nodes` / `skill_edges`. Every edge goes through
`domain.dag.build_acyclic_edges` first -- nothing writes an edge without passing
that choke point, which is what makes "the stored graph is a DAG" a property of
the system rather than a hope about the LLM.

Synchronous, because both callers (the seed script and the M5 reduce task) run
outside the request event loop.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.dag import (
    CandidateEdge,
    RejectedEdge,
    build_acyclic_edges,
    topological_depths,
    transitive_reduction,
)
from app.ingestion.toc import difficulty_from_depth
from app.models import Course, SkillEdge, SkillEdgeRejection, SkillNode


@dataclass(frozen=True, slots=True)
class ConceptSpec:
    slug: str
    title: str
    summary: str
    # `None` means "derive it from where this concept lands in the dependency
    # graph" -- see `persist_graph`. A number is an explicit override, used by
    # the seed and by the LLM path, where the model reports a difficulty
    # from reading the material itself.
    difficulty: int | None = None
    assessable: bool = True
    key_terms: tuple[str, ...] = ()
    source_chunk_ids: tuple[uuid.UUID, ...] = ()
    mention_count: int = 1
    # The outline heading this concept was found under, kept as PROVENANCE.
    # It groups and colours the canvas and tells a learner where to look in the
    # book; it is deliberately not a node and not an edge. See
    # `app.ingestion.toc.section_labels`.
    section: str | None = None


@dataclass(frozen=True, slots=True)
class GraphWriteResult:
    node_count: int
    edges_accepted: int
    edges_rejected: int
    edges_rendered: int  # after transitive reduction
    max_depth: int
    graph_version: int


# @spec CURR-GRAPH-001, CURR-GRAPH-002, CURR-GRAPH-003, CURR-GRAPH-004, CURR-GRAPH-005, CURR-GRAPH-006
def persist_graph(
    session: Session,
    course: Course,
    concepts: list[ConceptSpec],
    candidates: list[CandidateEdge],
    min_confidence: float = 0.35,
    prior_rejections: Sequence[RejectedEdge] = (),
) -> GraphWriteResult:
    """Replace a course's graph. Idempotent: same input in, same graph out.

    Order matters. Edges are resolved to a DAG *before* anything is written, so a
    graph that fails the acyclicity post-condition never reaches the database.

    `prior_rejections` carries refusals a caller already decided and is not asking
    to have re-decided. The curriculum compiler resolves acyclicity when it builds
    a draft, so by the time a version publishes, the edges it gave up on are no
    longer in the candidate set -- and this write fully replaces the course's
    rejection record. Without them the refusals would exist only as review rows on
    a version, and a course built through the curriculum path would report having
    refused nothing.
    """
    slugs = {concept.slug for concept in concepts}

    accepted, rejected = build_acyclic_edges(slugs, candidates, min_confidence=min_confidence)
    rejected = [*prior_rejections, *rejected]

    # Post-condition. build_acyclic_edges guarantees this by construction; if it
    # ever raises, the bug is in the builder and we want to know loudly rather
    # than persist a cyclic tree that renders as a knot.
    depths = topological_depths(slugs, accepted)
    max_depth = max(depths.values(), default=0)

    rendered = {(edge.prereq, edge.target) for edge in transitive_reduction(slugs, accepted)}

    # ── nodes: upsert on (course_id, slug) ────────────────────────────────
    existing_nodes = {
        node.slug: node
        for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course.id))
    }
    node_ids: dict[str, uuid.UUID] = {}

    for concept in concepts:
        node = existing_nodes.get(concept.slug)
        if node is None:
            node = SkillNode(course_id=course.id, slug=concept.slug)
            session.add(node)
        node.title = concept.title
        node.summary = concept.summary
        # Difficulty is a function of graph position, so it is resolved HERE --
        # after `topological_depths`, in the same transaction that writes
        # `depth`, from the same numbers. Storing a graph-derived value is safe
        # in a way storing a time-derived one is not: the graph only changes
        # when this function runs, and this function rewrites every node in the
        # course, so the value cannot drift while nobody is writing.
        node.difficulty = (
            concept.difficulty
            if concept.difficulty is not None
            else difficulty_from_depth(depths[concept.slug], max_depth)
        )
        node.assessable = concept.assessable
        node.section = concept.section
        node.key_terms = list(concept.key_terms)
        node.source_chunk_ids = list(concept.source_chunk_ids)
        node.mention_count = concept.mention_count
        node.depth = depths[concept.slug]
        session.flush()
        node_ids[concept.slug] = node.id

    # Concepts that vanished from a re-extraction. Cascades take their edges and
    # progress rows with them.
    for slug, node in existing_nodes.items():
        if slug not in slugs:
            session.delete(node)
    session.flush()

    # ── edges: full replace ───────────────────────────────────────────────
    session.execute(delete(SkillEdge).where(SkillEdge.course_id == course.id))
    session.execute(delete(SkillEdgeRejection).where(SkillEdgeRejection.course_id == course.id))
    session.flush()

    chunks_by_slug = {concept.slug: list(concept.source_chunk_ids) for concept in concepts}
    for edge in accepted:
        session.add(
            SkillEdge(
                course_id=course.id,
                prereq_id=node_ids[edge.prereq],
                target_id=node_ids[edge.target],
                confidence=edge.confidence,
                support=edge.support,
                rationale=edge.rationale or None,
                source_chunk_ids=chunks_by_slug.get(edge.target, []),
                # The full set is stored; only the reduced set is rendered.
                is_reduced=(edge.prereq, edge.target) in rendered,
            )
        )

    for refusal in rejected:
        session.add(
            SkillEdgeRejection(
                course_id=course.id,
                prereq_slug=refusal.prereq,
                target_slug=refusal.target,
                reason=refusal.reason,
                confidence=refusal.confidence,
                cycle_path=list(refusal.cycle_path),
            )
        )

    course.graph_version += 1
    course.status = "ready"
    session.flush()

    return GraphWriteResult(
        node_count=len(concepts),
        edges_accepted=len(accepted),
        edges_rejected=len(rejected),
        edges_rendered=len(rendered),
        max_depth=max(depths.values(), default=0),
        graph_version=course.graph_version,
    )
