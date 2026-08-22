"""Search, ask and the guided path over a really-ingested course.

The unit suite pins the ranking and the citation filter; what needs a live stack
is the wiring -- that Chroma is actually queried, that a citation resolves to a
node id the graph endpoint also returns, and that ownership is enforced.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.fixtures.sample_pdf import build_sample_pdf

CREDENTIALS = {"email": "explorer@example.com", "password": "hunter22-long-enough", "display_name": "Explorer"}
INTRUDER = {"email": "intruder@example.com", "password": "hunter22-long-enough", "display_name": "Intruder"}


@pytest.fixture
async def ingested(client: AsyncClient) -> dict:
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    created = await client.post("/api/courses", json={"title": "Explore Test"}, headers=headers)
    course_id = created.json()["id"]

    upload = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=headers,
        files={"file": ("sample.pdf", build_sample_pdf(), "application/pdf")},
    )
    assert upload.status_code == 202, upload.text

    graph = await client.get(f"/api/courses/{course_id}/graph", headers=headers)
    assert graph.status_code == 200 and graph.json()["nodes"], graph.text
    detail = await client.get(f"/api/courses/{course_id}", headers=headers)
    assert detail.status_code == 200, detail.text

    return {
        "course_id": course_id,
        "headers": headers,
        "graph": graph.json(),
        "documents": detail.json()["documents"],
    }


# ── search ────────────────────────────────────────────────────────────────


async def test_a_node_is_found_by_its_own_title(client: AsyncClient, ingested: dict) -> None:
    title = ingested["graph"]["nodes"][0]["title"]
    response = await client.get(
        f"/api/courses/{ingested['course_id']}/search", params={"q": title}, headers=ingested["headers"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"], body
    assert body["results"][0]["title"] == title
    assert body["results"][0]["score"] >= 0.84


async def test_search_reports_whether_the_vector_half_answered(client: AsyncClient, ingested: dict) -> None:
    """"nothing matched" and "semantic search is down" look identical otherwise."""
    response = await client.get(
        f"/api/courses/{ingested['course_id']}/search", params={"q": "vector"}, headers=ingested["headers"]
    )
    assert response.json()["semantic"] is True


async def test_a_query_that_matches_nothing_returns_an_empty_list_not_an_error(
    client: AsyncClient, ingested: dict
) -> None:
    response = await client.get(
        f"/api/courses/{ingested['course_id']}/search",
        params={"q": "zzzqqq-not-in-this-book"},
        headers=ingested["headers"],
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


async def test_search_on_another_users_course_is_a_404(client: AsyncClient, ingested: dict) -> None:
    """404, not 403 -- a 403 confirms the course id exists."""
    other = await client.post("/api/auth/register", json=INTRUDER)
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = await client.get(
        f"/api/courses/{ingested['course_id']}/search", params={"q": "anything"}, headers=headers
    )
    assert response.status_code == 404


# ── ask ───────────────────────────────────────────────────────────────────


async def test_an_answer_cites_a_node_the_graph_also_returns(client: AsyncClient, ingested: dict) -> None:
    """The whole point of citing NODES rather than pages: the citation has to be
    something the tree can select."""
    response = await client.post(
        f"/api/courses/{ingested['course_id']}/ask",
        json={"question": "what is a vector?"},
        headers=ingested["headers"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retrieved"] > 0
    known = {node["id"] for node in ingested["graph"]["nodes"]}
    document_ids = {document["id"] for document in ingested["documents"]}
    assert all(citation["node_id"] in known for citation in body["citations"])
    assert all(citation["source"]["document_id"] in document_ids for citation in body["citations"])


async def test_every_citation_quotes_material_it_names(client: AsyncClient, ingested: dict) -> None:
    response = await client.post(
        f"/api/courses/{ingested['course_id']}/ask",
        json={"question": "what is a vector?"},
        headers=ingested["headers"],
    )
    document_ids = {document["id"] for document in ingested["documents"]}
    for citation in response.json()["citations"]:
        assert len(citation["quote"]) >= 10
        assert citation["source"]["page_start"] >= 0
        assert citation["source"]["document_id"] in document_ids


async def test_asking_a_course_with_no_material_is_answered_not_500(client: AsyncClient) -> None:
    """A course created but never ingested. The endpoint a learner reaches for
    when stuck must not be the one that breaks."""
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    created = await client.post("/api/courses", json={"title": "Empty"}, headers=headers)

    response = await client.post(
        f"/api/courses/{created.json()['id']}/ask", json={"question": "anything at all"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "question": "anything at all",
        "answer": response.json()["answer"],
        "citations": [],
        "retrieved": 0,
    }


async def test_a_question_shorter_than_the_floor_is_rejected(client: AsyncClient, ingested: dict) -> None:
    response = await client.post(
        f"/api/courses/{ingested['course_id']}/ask", json={"question": "a"}, headers=ingested["headers"]
    )
    assert response.status_code == 422


# ── the guided path ───────────────────────────────────────────────────────


async def test_the_path_is_dependency_ordered_and_holds_no_containers(
    client: AsyncClient, ingested: dict
) -> None:
    response = await client.get(f"/api/courses/{ingested['course_id']}/path", headers=ingested["headers"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["steps"], body

    assessable = {node["id"]: node["assessable"] for node in ingested["graph"]["nodes"]}
    assert all(assessable[step["node_id"]] for step in body["steps"])
    # Depth is non-decreasing: that IS the dependency order.
    assert [step["depth"] for step in body["steps"]] == sorted(step["depth"] for step in body["steps"])


async def test_the_first_step_is_where_to_start(client: AsyncClient, ingested: dict) -> None:
    body = (await client.get(f"/api/courses/{ingested['course_id']}/path", headers=ingested["headers"])).json()

    assert body["next_node_id"] == body["steps"][0]["node_id"]
    assert body["completed"] == 0
    assert body["total"] == len(body["steps"])
    # Nothing has been drilled, so the walk starts on something that is not
    # locked -- a path whose first step you cannot take is not a path.
    assert body["steps"][0]["state"] != "locked"


async def test_the_path_of_an_empty_course_is_empty_not_an_error(client: AsyncClient) -> None:
    registered = await client.post("/api/auth/register", json=CREDENTIALS)
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    created = await client.post("/api/courses", json={"title": "Empty"}, headers=headers)

    response = await client.get(f"/api/courses/{created.json()['id']}/path", headers=headers)

    assert response.status_code == 200
    assert response.json()["steps"] == []
    assert response.json()["next_node_id"] is None
