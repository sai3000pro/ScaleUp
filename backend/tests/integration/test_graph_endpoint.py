"""End of the ingest chain: extraction, the graph endpoint, and the Neo4j mirror."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.domain.dag import CandidateEdge, topological_depths
from app.models import SkillEdge, SkillNode
from app.repositories import neo4j_repo
from tests.fixtures.sample_pdf import build_sample_pdf

CREDENTIALS = {"email": "grapher@example.com", "password": "hunter22-long-enough", "display_name": "Grapher"}


@pytest.fixture
async def course_with_graph(client: AsyncClient) -> dict:
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    created = await client.post("/api/courses", json={"title": "Extraction Test"}, headers=headers)
    course_id = created.json()["id"]

    upload = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=headers,
        files={"file": ("sample.pdf", build_sample_pdf(), "application/pdf")},
    )
    assert upload.status_code == 202

    job = await client.get(f"/api/jobs/{upload.json()['job_id']}", headers=headers)
    graph = await client.get(f"/api/courses/{course_id}/graph", headers=headers)
    assert graph.status_code == 200, graph.text

    return {"course_id": uuid.UUID(course_id), "headers": headers, "job": job.json(), "graph": graph.json()}


def test_extraction_produced_nodes(course_with_graph: dict) -> None:
    assert course_with_graph["graph"]["nodes"], "extraction produced no skill nodes"
    detail = course_with_graph["job"]["stage_detail"]
    assert detail["windows"] >= 1
    assert detail["concepts_merged"] >= 1


def test_pipeline_reached_succeeded_through_every_stage(course_with_graph: dict) -> None:
    job = course_with_graph["job"]
    assert job["state"] == "succeeded", job
    assert job["percent"] == 100.0
    assert job["stage_detail"]["failed_windows"] == 0


def test_the_stored_graph_is_acyclic(course_with_graph: dict) -> None:
    """The guarantee the whole extraction pipeline exists to preserve."""
    course_id = course_with_graph["course_id"]
    with sync_session() as session:
        slug_by_id = {
            node.id: node.slug for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course_id))
        }
        edges = [
            CandidateEdge(slug_by_id[e.prereq_id], slug_by_id[e.target_id], e.confidence)
            for e in session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id))
        ]

    topological_depths(set(slug_by_id.values()), edges)  # raises on a cycle


def test_rendered_edges_are_a_subset_of_stored_edges(course_with_graph: dict) -> None:
    course_id = course_with_graph["course_id"]
    with sync_session() as session:
        stored = session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id)).all()

    rendered = course_with_graph["graph"]["edges"]
    assert len(rendered) <= len(stored)
    assert len(rendered) == sum(1 for edge in stored if edge.is_reduced)


async def test_verified_edge_evidence_reaches_the_graph_api(
    course_with_graph: dict, client: AsyncClient
) -> None:
    """An accepted quote must survive persistence and the API projection."""
    course_id = course_with_graph["course_id"]
    rationale = "The source passage explicitly states that vectors are required first."

    with sync_session() as session:
        edge = session.scalars(
            select(SkillEdge).where(
                SkillEdge.course_id == course_id,
                SkillEdge.is_reduced.is_(True),
            )
        ).first()
        assert edge is not None
        edge.rationale = rationale
        session.commit()
        edge_id = f"{edge.prereq_id}->{edge.target_id}"

    response = await client.get(
        f"/api/courses/{course_id}/graph",
        headers=course_with_graph["headers"],
    )
    assert response.status_code == 200, response.text
    rendered = next(item for item in response.json()["edges"] if item["id"] == edge_id)
    assert rendered["rationale"] == rationale


def test_every_node_carries_a_derived_state_and_progress(course_with_graph: dict) -> None:
    valid = {"locked", "available", "learning", "decaying", "mastered"}
    for node in course_with_graph["graph"]["nodes"]:
        progress = node["progress"]
        assert progress["state"] in valid
        assert progress["exp"] == 0
        assert progress["level"] == 0
        assert progress["mastery"] == 0.0
        assert progress["proficiency"] == 0.0  # never reviewed
        assert progress["overdue_days"] == 0.0


def test_stats_account_for_every_node(course_with_graph: dict) -> None:
    graph = course_with_graph["graph"]
    stats = graph["stats"]
    assert stats["total"] == len(graph["nodes"])
    assert stats["locked"] + stats["available"] + stats["learning"] + stats["decaying"] + stats["mastered"] == stats["total"]


def test_a_fresh_user_has_at_least_one_available_node(course_with_graph: dict) -> None:
    """A tree where nothing is reachable is a tree nobody can start."""
    assert course_with_graph["graph"]["stats"]["available"] >= 1


def test_nodes_are_ordered_by_depth(course_with_graph: dict) -> None:
    depths = [node["depth"] for node in course_with_graph["graph"]["nodes"]]
    assert depths == sorted(depths)


def test_locked_nodes_name_what_blocks_them(course_with_graph: dict) -> None:
    for node in course_with_graph["graph"]["nodes"]:
        if node["progress"]["state"] == "locked":
            assert node["blocked_by"], f"{node['slug']} is locked but names no blocker"


def test_neo4j_projection_matches_postgres(course_with_graph: dict) -> None:
    course_id = course_with_graph["course_id"]
    # One scoped session. A session left open here holds an ACCESS SHARE lock,
    # and the next test's TRUNCATE (which needs ACCESS EXCLUSIVE) blocks on it
    # forever -- a deadlock that only shows up when tests run in order.
    with sync_session() as session:
        pg_edges = session.scalars(select(SkillEdge).where(SkillEdge.course_id == course_id)).all()
        stale = neo4j_repo.is_stale(session, course_id)

    assert course_with_graph["job"]["stage_detail"]["neo4j_edges"] == len(pg_edges)
    # And the projection stamped the version it was built from.
    assert not stale


def test_prerequisite_closure_is_queryable(course_with_graph: dict) -> None:
    """The traversal Neo4j is actually here for."""
    deepest = max(course_with_graph["graph"]["nodes"], key=lambda n: n["depth"])
    closure = neo4j_repo.prerequisite_closure(uuid.UUID(deepest["id"]))

    if deepest["depth"] > 0:
        assert closure, f"node at depth {deepest['depth']} reported no prerequisites"
        assert all(entry["distance"] >= 1 for entry in closure)


async def test_graph_is_not_readable_by_another_user(course_with_graph: dict, client: AsyncClient) -> None:
    other = await client.post(
        "/api/auth/register",
        json={"email": "peeker@example.com", "password": "hunter22-long-enough", "display_name": "Peeker"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.get(f"/api/courses/{course_with_graph['course_id']}/graph", headers=headers)
    assert response.status_code == 404
