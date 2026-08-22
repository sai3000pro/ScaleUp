"""Neo4j projection of the skill graph.

**Neo4j never receives an authoritative write.** It is rebuilt from Postgres by
this module, which reduces consistency from a distributed-write problem to a
single monitorable question: is the projection's `graph_version` behind the
course's? A read path that finds it stale falls back to Postgres and re-enqueues
the projection rather than serving wrong structure.

The traversal that justifies its existence is the cross-course prerequisite
closure at the bottom of this file -- a variable-length walk that a recursive CTE
can express but not as directly.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from functools import lru_cache

from neo4j import GraphDatabase
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Course, SkillEdge, SkillNode

CONSTRAINTS = (
    "CREATE CONSTRAINT skill_id IF NOT EXISTS FOR (s:Skill) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT course_id IF NOT EXISTS FOR (c:Course) REQUIRE c.id IS UNIQUE",
    "CREATE INDEX skill_course IF NOT EXISTS FOR (s:Skill) ON (s.courseId)",
)


@lru_cache(maxsize=1)
def _driver():
    settings = get_settings()
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


@contextmanager
def session_scope():
    with _driver().session() as session:
        yield session


def ensure_constraints() -> None:
    with session_scope() as session:
        for statement in CONSTRAINTS:
            session.run(statement)


def project_course(db: Session, course_id: uuid.UUID) -> int:
    """Rebuild one course's subgraph from Postgres. Returns the edge count.

    Full rebuild rather than an incremental diff: a course is a few hundred
    nodes, the write is idempotent, and a diff would need change tracking that
    would itself be a source of drift.
    """
    course = db.get(Course, course_id)
    if course is None:
        raise LookupError(f"course {course_id} not found")

    nodes = list(db.scalars(select(SkillNode).where(SkillNode.course_id == course_id)))
    edges = list(db.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id)))

    node_rows = [
        {
            "id": str(node.id),
            "slug": node.slug,
            "title": node.title,
            "difficulty": node.difficulty,
            "depth": node.depth,
            "assessable": node.assessable,
        }
        for node in nodes
    ]
    edge_rows = [{"prereq": str(edge.prereq_id), "target": str(edge.target_id)} for edge in edges]

    ensure_constraints()
    with session_scope() as session:
        session.execute_write(_rebuild, str(course_id), course.graph_version, node_rows, edge_rows)

    return len(edge_rows)


def _rebuild(tx, course_id: str, graph_version: int, nodes: list[dict], edges: list[dict]) -> None:
    # Detach-delete the course's existing subgraph so removed concepts do not
    # linger. Scoped to one course, so other courses are untouched.
    tx.run("MATCH (s:Skill {courseId: $courseId}) DETACH DELETE s", courseId=course_id)

    tx.run(
        """
        UNWIND $nodes AS row
        MERGE (s:Skill {id: row.id})
        SET s.courseId   = $courseId,
            s.slug       = row.slug,
            s.title      = row.title,
            s.difficulty = row.difficulty,
            s.depth      = row.depth,
            s.assessable = row.assessable
        """,
        nodes=nodes,
        courseId=course_id,
    )

    tx.run(
        """
        UNWIND $edges AS row
        MATCH (p:Skill {id: row.prereq})
        MATCH (t:Skill {id: row.target})
        MERGE (p)-[:PREREQUISITE_OF]->(t)
        """,
        edges=edges,
    )

    tx.run(
        "MERGE (c:Course {id: $courseId}) SET c.graphVersion = $graphVersion",
        courseId=course_id,
        graphVersion=graph_version,
    )


def projected_version(course_id: uuid.UUID) -> int | None:
    """The graph_version this projection was built from, or None if absent."""
    with session_scope() as session:
        record = session.run(
            "MATCH (c:Course {id: $courseId}) RETURN c.graphVersion AS version",
            courseId=str(course_id),
        ).single()
    return None if record is None else record["version"]


def is_stale(db: Session, course_id: uuid.UUID) -> bool:
    course = db.get(Course, course_id)
    if course is None:
        return True
    return projected_version(course_id) != course.graph_version


def prerequisite_closure(node_id: uuid.UUID, max_depth: int = 8) -> list[dict]:
    """Every skill that must be learned before `node_id`, with its distance.

    This is the query Neo4j is actually here for: it spans courses without
    caring which course a prerequisite came from, which is the foundation for
    cross-course skill carry-over.
    """
    with session_scope() as session:
        records = session.run(
            f"""
            MATCH (target:Skill {{id: $nodeId}})
            MATCH path = (p:Skill)-[:PREREQUISITE_OF*1..{int(max_depth)}]->(target)
            WITH DISTINCT p, min(length(path)) AS distance
            RETURN p.id AS id, p.title AS title, p.courseId AS courseId, distance
            ORDER BY distance DESC, p.title
            """,
            nodeId=str(node_id),
        )
        return [dict(record) for record in records]


def clear_all() -> None:
    """Wipe the projection. For tests and for a full rebuild."""
    with session_scope() as session:
        session.run("MATCH (n) DETACH DELETE n")
