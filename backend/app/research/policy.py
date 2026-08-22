"""Conservative source-policy metadata and explicit verification.

Search proposals do not crawl candidate pages. They receive an honest
``review_required`` state and links for learner review. An explicit policy check
may later fetch only the candidate's robots file and its own page, using the
same SSRF-safe bounded fetcher as ingestion. A detected license declaration is
evidence to review, not a grant of permission; robots disallowance blocks
approval regardless of acknowledgement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from app.ingestion.fetch import FetchedResource, UrlFetchError, fetch_url
from app.research.providers import ResearchResult

POLICY_ROBOTS_MAX_BYTES = 256 * 1024
POLICY_PAGE_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    status: str
    robots_url: str
    robots_status: str
    license_status: str
    reasons: list[str]
    checked: bool = False


def _robots_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


# @spec CURR-SOURCE-005
def assess_source_policy(result: ResearchResult) -> SourcePolicy:
    """Return proposal metadata without making an unsolicited request."""
    robots_url = _robots_url(result.url)
    reasons = [
        "robots.txt has not been checked yet",
        "license was not identified from search metadata",
    ]
    return SourcePolicy(
        status="review_required",
        robots_url=robots_url,
        robots_status="not_checked",
        license_status="not_identified",
        reasons=reasons,
    )


def _robots_pattern_matches(pattern: str, path: str) -> bool:
    """Match the common robots path syntax conservatively."""
    if not pattern:
        return False
    expression = re.escape(pattern).replace(r"\*", ".*")
    if expression.endswith(r"\$"):
        expression = expression[:-2] + "$"
    return re.match(rf"^{expression}", path) is not None


def _robots_allows(robots_text: str, source_url: str) -> bool:
    """Evaluate the ``User-agent: *`` group for one source URL.

    This deliberately supports the path rules needed for a learner-facing
    safety signal, not every crawler-specific extension. If no wildcard group
    applies, the result is allowed; a disallow rule always wins only when it is
    the longest matching rule, with ``Allow`` winning an equal-length tie.
    """
    path_parts = urlparse(source_url)
    path = path_parts.path or "/"
    if path_parts.query:
        path = f"{path}?{path_parts.query}"

    in_wildcard_group = False
    rules: list[tuple[bool, str]] = []
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            pass
        else:
            directive, value = line.split(":", 1)
            directive = directive.strip().casefold()
            value = value.strip()
            if directive == "user-agent":
                in_wildcard_group = value == "*"
            elif in_wildcard_group and directive in {"allow", "disallow"}:
                rules.append((directive == "allow", value))

    matches = [(len(pattern), allowed) for allowed, pattern in rules if _robots_pattern_matches(pattern, path)]
    if not matches:
        return True
    longest = max(length for length, _allowed in matches)
    return any(allowed for length, allowed in matches if length == longest)


def _license_reference(resource: FetchedResource) -> str | None:
    """Find an explicit HTML license declaration, without interpreting it."""
    content_type = resource.content_type.casefold()
    if "html" not in content_type and not resource.payload.lstrip().startswith((b"<", b"<!doctype")):
        return None

    text = resource.payload.decode("utf-8", errors="replace")
    patterns = (
        r"<link[^>]+rel=[\"'][^\"']*\blicense\b[^\"']*[\"'][^>]+href=[\"']([^\"']+)",
        r"<meta[^>]+(?:name|property)=[\"'](?:license|dcterms\.license)[\"'][^>]+content=[\"']([^\"']+)",
        r"[\"']license[\"']\s*:\s*[\"']([^\"']+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return urljoin(resource.url, match.group(1).strip())
    return None


def verify_source_policy(
    result: ResearchResult,
    *,
    fetch: Callable[..., FetchedResource] = fetch_url,
) -> SourcePolicy:
    """Check one source's robots rules and explicit license declaration.

    Both requests are bounded and pass through the SSRF-safe fetch seam. Any
    fetch failure becomes an explicit unavailable state rather than an approval
    signal. ``status`` is never ``clear``: a declaration still requires the
    learner to confirm that their intended use is permitted.
    """
    robots_url = _robots_url(result.url)
    reasons: list[str] = []

    try:
        robots = fetch(robots_url, max_bytes=POLICY_ROBOTS_MAX_BYTES)
    except UrlFetchError as exc:
        robots_status = "unavailable"
        reasons.append(f"robots.txt could not be checked: {exc}")
    else:
        robots_text = robots.payload.decode("utf-8", errors="replace")
        if _robots_allows(robots_text, result.url):
            robots_status = "checked_allowed"
            reasons.append("robots.txt does not disallow this source path for the wildcard agent")
        else:
            robots_status = "checked_disallowed"
            reasons.append("robots.txt disallows this source path for the wildcard agent")

    try:
        page = fetch(result.url, max_bytes=POLICY_PAGE_MAX_BYTES)
    except UrlFetchError as exc:
        license_status = "unavailable"
        reasons.append(f"source page could not be checked for a license: {exc}")
    else:
        license = _license_reference(page)
        if license is None:
            license_status = "not_identified"
            reasons.append("no explicit license declaration was found on the source page")
        else:
            license_status = "identified"
            reasons.append(f"source page declares a license at {license}; permission still requires review")

    status = "blocked" if robots_status == "checked_disallowed" else "review_required"
    return SourcePolicy(
        status=status,
        robots_url=robots_url,
        robots_status=robots_status,
        license_status=license_status,
        reasons=reasons,
        checked=True,
    )
