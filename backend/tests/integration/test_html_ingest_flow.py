"""HTML upload, URL ingestion, and the mixed-outline course.

The last of those is the one worth having: a course holding one well-outlined
document plus a short one used to silently drop the short one's content from the
tree while leaving its chunks in Chroma, and every status the user could see said
the ingest succeeded.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import sync_session
from app.models import Chunk, Document, SkillNode
from tests.fixtures.sample_html import BOILERPLATE_MARKERS, SECTIONS, build_sample_html
from tests.fixtures.sample_pdf import build_sample_pdf

CREDENTIALS = {"email": "reader@example.com", "password": "hunter22-long-enough", "display_name": "Reader"}


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/auth/register", json=CREDENTIALS)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def course_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    response = await client.post("/api/courses", json={"title": "Linear Algebra"}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def upload(client: AsyncClient, headers: dict[str, str], course: str, name: str, payload: bytes) -> dict:
    response = await client.post(
        f"/api/courses/{course}/documents",
        headers=headers,
        files={"file": (name, payload, "application/octet-stream")},
    )
    assert response.status_code == 202, response.text
    return response.json()


# ── upload ────────────────────────────────────────────────────────────────


async def test_an_html_upload_becomes_a_graph_of_its_own_headings(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """The whole feature's claim, end to end and falsifiable."""
    body = await upload(client, auth_headers, course_id, "algebra.html", build_sample_html())
    assert body["document"]["source_type"] == "html"

    job = await client.get(f"/api/jobs/{body['job_id']}", headers=auth_headers)
    assert job.json()["state"] == "succeeded", job.text

    graph = await client.get(f"/api/courses/{course_id}/graph", headers=auth_headers)
    titles = {node["title"] for node in graph.json()["nodes"]}
    for _, heading, _ in SECTIONS:
        assert heading in titles, sorted(titles)


async def test_boilerplate_never_reaches_a_stored_chunk(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    await upload(client, auth_headers, course_id, "algebra.html", build_sample_html())

    with sync_session() as session:
        texts = " ".join(session.scalars(select(Chunk.text)))
        paths = " ".join(p or "" for p in session.scalars(select(Chunk.section_path)))
    assert texts
    for marker in BOILERPLATE_MARKERS:
        assert marker not in texts
        assert marker not in paths


async def test_the_content_type_header_is_not_believed(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """A .pdf name and an application/pdf header over HTML bytes is still HTML."""
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("lies.pdf", build_sample_html(), "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["document"]["source_type"] == "html"


async def test_an_unreadable_format_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        headers=auth_headers,
        files={"file": ("book.epub", b"PK\x03\x04not really an epub", "application/epub+zip")},
    )
    assert response.status_code == 415


# ── url ───────────────────────────────────────────────────────────────────


async def test_ingesting_a_url_records_it_as_provenance(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No network: the fetch is replaced at the service seam.

    `source_uri` is the URL and `filename` is the page's own `<title>`, because
    a learner reading a document list wants the article's name, not a slug from
    the path.
    """
    from app.ingestion.fetch import FetchedResource
    from app.services import ingest_service

    url = "https://example.com/linear-algebra?utm_source=newsletter"
    monkeypatch.setattr(
        ingest_service,
        "fetch_url",
        lambda target, **kwargs: FetchedResource(url=url, payload=build_sample_html(), content_type="text/html"),
    )

    response = await client.post(
        f"/api/courses/{course_id}/documents/url", headers=auth_headers, json={"url": url}
    )
    assert response.status_code == 202, response.text
    assert response.json()["document"]["source_type"] == "html"
    assert response.json()["document"]["filename"] == "Linear Algebra, Abridged"

    with sync_session() as session:
        document = session.scalars(select(Document)).one()
    assert document.source_uri == url
    assert document.storage_path.endswith(".html")


async def test_a_refused_url_is_a_400_with_the_reason(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """Reaches the real guard -- no transport is involved, so nothing is fetched."""
    response = await client.post(
        f"/api/courses/{course_id}/documents/url",
        headers=auth_headers,
        json={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert response.status_code == 400, response.text
    assert "private or reserved" in response.json()["detail"]


async def test_a_non_http_scheme_is_a_400(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    response = await client.post(
        f"/api/courses/{course_id}/documents/url",
        headers=auth_headers,
        json={"url": "file:///etc/passwd"},
    )
    assert response.status_code == 400
    assert "http and https" in response.json()["detail"]


async def test_the_url_endpoint_is_owner_scoped(client: AsyncClient, course_id: str) -> None:
    other = await client.post(
        "/api/auth/register",
        json={"email": "nosy@example.com", "password": "hunter22-long-enough", "display_name": "Nosy"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.post(
        f"/api/courses/{course_id}/documents/url", headers=headers, json={"url": "https://example.com/"}
    )
    assert response.status_code == 404


async def test_a_mock_transport_carries_a_page_all_the_way_through(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real fetch code path, with only the socket replaced.

    Exercises `assert_public_url` -> redirect -> streaming read -> sniff ->
    parse -> chunk -> graph, which is everything the endpoint does except open a
    connection.
    """
    import socket

    from app.ingestion import fetch
    from app.services import ingest_service

    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/old":
            return httpx.Response(301, headers={"location": "/article"})
        return httpx.Response(200, content=build_sample_html(), headers={"content-type": "text/html"})

    monkeypatch.setattr(
        ingest_service,
        "fetch_url",
        lambda url, **kwargs: fetch.fetch_url(
            url, transport=httpx.MockTransport(handler), resolver=resolver
        ),
    )

    response = await client.post(
        f"/api/courses/{course_id}/documents/url",
        headers=auth_headers,
        json={"url": "https://example.com/old"},
    )
    assert response.status_code == 202, response.text

    with sync_session() as session:
        document = session.scalars(select(Document)).one()
    assert document.source_uri == "https://example.com/article", "the FINAL url is the provenance"

    graph = await client.get(f"/api/courses/{course_id}/graph", headers=auth_headers)
    assert "The Dot Product" in {node["title"] for node in graph.json()["nodes"]}


# ── the mixed-outline drop ────────────────────────────────────────────────


async def test_a_document_with_too_thin_an_outline_still_reaches_the_tree(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """`min_toc_entries` is judged per document; the fallback must be too.

    Before this, `extract_graph` branched on whether the COURSE produced any
    outline concepts at all. One outlined book therefore suppressed the LLM
    fallback for every other document in the course, and a short article
    contributed nothing to the tree while its chunks sat in Chroma being
    retrieved as drill context for a node from a different book.
    """
    thin = (
        b"<!DOCTYPE html><html><head><title>Eigenvalues</title></head><body><main>"
        b"<h1>Eigenvalues</h1>"
        b"<p>An eigenvector of a square matrix is a nonzero vector whose direction is "
        b"unchanged when the matrix is applied to it, and the eigenvalue is the factor "
        b"by which it is scaled. Eigenvalues are the roots of the characteristic "
        b"polynomial, which is the determinant of the matrix minus lambda times the "
        b"identity. They determine stability, resonance, and the long-run behaviour of "
        b"iterated linear maps.</p>"
        b"</main></body></html>"
    )

    await upload(client, auth_headers, course_id, "book.pdf", build_sample_pdf())
    await upload(client, auth_headers, course_id, "eigen.html", thin)

    with sync_session() as session:
        documents = {d.filename: d.id for d in session.scalars(select(Document))}
        node_chunk_ids = {
            cid
            for node in session.scalars(select(SkillNode))
            for cid in (node.source_chunk_ids or [])
        }
        thin_chunk_ids = {
            c.id for c in session.scalars(select(Chunk).where(Chunk.document_id == documents["eigen.html"]))
        }

    assert thin_chunk_ids, "the thin document produced no chunks at all"
    # One outline entry is below `min_toc_entries`, so this document takes the
    # LLM fallback -- but it must reach the tree by SOME path.
    assert thin_chunk_ids & node_chunk_ids, (
        "the short document's chunks are in Chroma and owned by no node: "
        "the per-course fallback branch is back"
    )


async def test_the_outlined_document_is_unharmed_by_the_thin_one(
    client: AsyncClient, auth_headers: dict[str, str], course_id: str
) -> None:
    """The fallback must add nodes, not replace the outline's."""
    await upload(client, auth_headers, course_id, "algebra.html", build_sample_html())
    before = (await client.get(f"/api/courses/{course_id}/graph", headers=auth_headers)).json()

    await upload(
        client,
        auth_headers,
        course_id,
        "short.html",
        b"<html><head><title>Traces</title></head><body><main><h1>Trace</h1>"
        b"<p>The trace of a square matrix is the sum of its diagonal entries, and it "
        b"equals the sum of the eigenvalues counted with multiplicity. It is invariant "
        b"under a change of basis, which is what makes it a property of the linear map "
        b"rather than of the particular matrix chosen to represent that map. The trace "
        b"is linear, and the trace of a product is unchanged by cyclic permutation of "
        b"its factors.</p></main></body></html>",
    )
    after = (await client.get(f"/api/courses/{course_id}/graph", headers=auth_headers)).json()

    before_titles = {node["title"] for node in before["nodes"]}
    after_titles = {node["title"] for node in after["nodes"]}
    assert before_titles <= after_titles, before_titles - after_titles
    assert len(after["nodes"]) > len(before["nodes"])
