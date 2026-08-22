from app.ingestion.fetch import FetchedResource
from app.research.policy import assess_source_policy, verify_source_policy
from app.research.providers import ResearchResult


def test_policy_assessment_is_explicit_and_does_not_claim_verification() -> None:
    result = ResearchResult(
        title="Vectors",
        url="https://example.edu/math/vectors",
        snippet="A source about vectors.",
        published_at=None,
        domain="example.edu",
    )

    policy = assess_source_policy(result)

    assert policy.status == "review_required"
    assert policy.robots_url == "https://example.edu/robots.txt"
    assert policy.robots_status == "not_checked"
    assert policy.license_status == "not_identified"
    assert len(policy.reasons) == 2


def test_explicit_check_records_robots_and_license_evidence() -> None:
    result = ResearchResult(
        title="Vectors",
        url="https://example.edu/math/vectors",
        snippet="A source about vectors.",
        published_at=None,
        domain="example.edu",
    )

    def fetch(url: str, *, max_bytes: int) -> FetchedResource:
        if url.endswith("/robots.txt"):
            return FetchedResource(
                url=url,
                payload=b"User-agent: *\nAllow: /math/\n",
                content_type="text/plain",
            )
        return FetchedResource(
            url=url,
            payload=b'<html><head><link rel="license" href="/license"></head></html>',
            content_type="text/html",
        )

    policy = verify_source_policy(result, fetch=fetch)

    assert policy.status == "review_required"
    assert policy.checked is True
    assert policy.robots_status == "checked_allowed"
    assert policy.license_status == "identified"
    assert any("permission still requires review" in reason for reason in policy.reasons)


def test_robots_disallowance_blocks_even_when_a_license_is_declared() -> None:
    result = ResearchResult(
        title="Private notes",
        url="https://example.edu/private/notes",
        snippet="A source.",
        published_at=None,
        domain="example.edu",
    )

    def fetch(url: str, *, max_bytes: int) -> FetchedResource:
        if url.endswith("/robots.txt"):
            return FetchedResource(
                url=url,
                payload=b"User-agent: *\nDisallow: /private/\n",
                content_type="text/plain",
            )
        return FetchedResource(
            url=url,
            payload=b'<html><head><meta name="license" content="https://example.edu/license"></head></html>',
            content_type="text/html",
        )

    policy = verify_source_policy(result, fetch=fetch)

    assert policy.status == "blocked"
    assert policy.robots_status == "checked_disallowed"
    assert policy.license_status == "identified"
