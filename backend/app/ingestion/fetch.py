"""Fetch a URL safely enough to hand its bytes to a parser.

The feature is "paste a link to an article". The risk is that the server, not
the user, is the one making the request -- so every address the backend can
reach and the browser cannot is now reachable *through* the backend by anyone
who can type a URL. That is SSRF, and on a machine with any cloud provider
underneath it the payoff is concrete: `http://169.254.169.254/latest/meta-data/`
returns instance credentials.

The attack to hold in mind is not a link to `169.254.169.254` -- a scheme and
range check on the submitted string stops that. It is a link to an ordinary
public host that answers `302 Location: http://169.254.169.254/...`. Which is
why redirects are followed manually and **the entire check re-runs on every
hop**, and why a response body is never trusted to be what its URL suggested.

Layers, all required, none of them sufficient alone:

  1. scheme allowlist -- http/https, so `file://`, `gopher://`, and the
     `redis://` your own broker speaks are all simply unspellable;
  2. no credentials in the URL -- `http://user:pass@host/` is how a fetcher gets
     talked into authenticating to something;
  3. port allowlist -- 80/443, so the internal Postgres on 5433 and the Neo4j
     bolt port are not addressable even on a host that resolves publicly;
  4. DNS resolution up front, then **every** resolved address checked -- a
     hostname with one public and one loopback A record is a real bypass, so
     the rule is "reject if ANY address is private", not "accept if one is
     public";
  5. IPv4-in-IPv6 unmapped before the range check -- `::ffff:169.254.169.254`
     is not private to an IPv6 test and is the metadata endpoint to a kernel;
  6. a streaming byte cap, explicit timeouts, and `trust_env=False` so an
     `HTTP_PROXY` in the environment cannot route around all of the above.

**Residual risk, accepted and written down: DNS rebinding.** The address is
checked and then httpx resolves the name again to connect, and a hostile
resolver can answer differently the second time. Closing it needs a transport
that connects to the pinned IP and carries the original Host header. For a
single-user tool on a laptop that is not worth the custom transport; if this
ever runs anywhere multi-tenant, that is the fix and it goes here.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import get_settings

__all__ = ["FetchedResource", "UrlFetchError", "assert_public_url", "fetch_url"]

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[..., list]


class UrlFetchError(ValueError):
    """The URL was refused, or fetching it failed.

    One exception type for both, because the caller's response is the same
    either way and the distinction between "we would not" and "we could not"
    belongs in the message, not the type.
    """


@dataclass(frozen=True, slots=True)
class FetchedResource:
    # The URL actually fetched, after redirects. Stored as provenance, and it is
    # the one worth showing a user -- the one they pasted may be a shortener.
    url: str
    payload: bytes
    content_type: str


def _unmap(address: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Reduce an IPv6 address to the IPv4 address hiding inside it, if any.

    Three separate encodings, and each has been used to smuggle a private
    address past a naive check: `::ffff:a.b.c.d` (v4-mapped), `2002:AABB:CCDD::`
    (6to4), and Teredo, which carries the *server's* v4 address. All three
    resolve to a v4 destination in the end, so all three are checked as one.
    """
    if isinstance(address, ipaddress.IPv6Address):
        for embedded in (address.ipv4_mapped, address.sixtofour, address.teredo[0] if address.teredo else None):
            if embedded is not None:
                return embedded
    return address


def _is_forbidden(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    resolved = _unmap(address)
    return (
        resolved.is_private
        or resolved.is_loopback
        or resolved.is_link_local
        or resolved.is_reserved
        or resolved.is_multicast
        or resolved.is_unspecified
        or not resolved.is_global
    )


# @spec CURR-SOURCE-004
def assert_public_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    """Refuse anything that is not a plain public web address. Returns the URL.

    `resolver` is injected rather than imported so the test suite can describe a
    hostile DNS answer without touching the network. Monkeypatching
    `socket.getaddrinfo` globally would have done it too, and would also have
    broken every Postgres connection the integration suite opens.
    """
    settings = get_settings()

    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise UrlFetchError(f"Not a valid URL: {exc}") from exc

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlFetchError(f"Only http and https URLs can be ingested (got {parts.scheme!r}).")

    if parts.username or parts.password:
        raise UrlFetchError("URLs carrying credentials are not accepted.")

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        # urlsplit defers parsing the port, so a garbage one raises here.
        raise UrlFetchError(f"Not a valid URL: {exc}") from exc

    if not hostname:
        raise UrlFetchError("That URL has no host.")

    port = port or DEFAULT_PORTS[parts.scheme.lower()]
    if port not in ALLOWED_PORTS:
        raise UrlFetchError(f"Only ports 80 and 443 can be fetched (got {port}).")

    if settings.url_fetch_allow_private_hosts:
        # Development escape hatch. `_reject_development_defaults_when_deployed`
        # refuses to start with this on, so it cannot reach anything real.
        return url

    try:
        infos = resolver(hostname, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlFetchError(f"Could not resolve {hostname}.") from exc

    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise UrlFetchError(f"Could not resolve {hostname}.")

    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw.split("%")[0])
        except ValueError as exc:
            raise UrlFetchError(f"{hostname} resolved to something that is not an address.") from exc
        # ANY private answer is fatal. Accepting the host because one of its
        # records is public is the bypass: an attacker controls the record set
        # and only needs the connection to pick the other one.
        if _is_forbidden(address):
            raise UrlFetchError(
                f"{hostname} resolves to a private or reserved address ({address}); refusing to fetch it."
            )

    return url


def _read_capped(response: httpx.Response, cap: int) -> bytes:
    """Stream the body, stopping the moment it exceeds the cap.

    Streaming rather than `response.content`: the point of a limit is not to
    report that a 4 GB page was too big, it is never to hold 4 GB. The
    `Content-Length` check above it is a courtesy that saves the transfer when
    the server is honest, and cannot be relied on when it is not.
    """
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        raise UrlFetchError(f"That page is larger than the {cap // (1024 * 1024)} MB limit.")

    chunks: list[bytes] = []
    total = 0
    for block in response.iter_bytes():
        total += len(block)
        if total > cap:
            raise UrlFetchError(f"That page is larger than the {cap // (1024 * 1024)} MB limit.")
        chunks.append(block)
    return b"".join(chunks)


# @spec CURR-SOURCE-003
def fetch_url(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver = socket.getaddrinfo,
    max_bytes: int | None = None,
) -> FetchedResource:
    """Fetch a public web page. Blocking -- call it off the event loop.

    Redirects are followed by hand, three hops at most, with `assert_public_url`
    re-run on each. httpx's own `follow_redirects=True` would follow them
    inside the client where nothing can inspect the intermediate URLs, which
    turns every one of the checks above into a check of the first hop only.
    """
    settings = get_settings()
    current = assert_public_url(url, resolver=resolver)
    byte_cap = max_bytes if max_bytes is not None else settings.url_fetch_max_bytes

    client = httpx.Client(
        follow_redirects=False,
        # No proxies, no CA bundle, no timeout from the environment. An
        # `HTTP_PROXY` set on the host would send every fetch through a third
        # party that our address checks have said nothing about.
        trust_env=False,
        timeout=httpx.Timeout(settings.url_fetch_timeout_seconds),
        transport=transport,
        headers={
            "User-Agent": settings.url_fetch_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
            "Accept-Language": "en",
        },
    )

    try:
        for _ in range(settings.url_fetch_max_redirects + 1):
            with client.stream("GET", current) as response:
                location = response.headers.get("location")
                if response.is_redirect and location:
                    # Resolve against the URL we actually asked for, then check
                    # the result from scratch. A relative Location is common and
                    # a cross-scheme one is the attack.
                    current = assert_public_url(urljoin(current, location), resolver=resolver)
                elif response.status_code >= 400:
                    raise UrlFetchError(f"That URL returned HTTP {response.status_code}.")
                else:
                    payload = _read_capped(response, byte_cap)
                    if not payload:
                        raise UrlFetchError("That URL returned an empty response.")
                    return FetchedResource(
                        url=str(response.url),
                        payload=payload,
                        content_type=response.headers.get("content-type", ""),
                    )

        raise UrlFetchError(f"That URL redirected more than {settings.url_fetch_max_redirects} times.")
    except httpx.HTTPError as exc:
        raise UrlFetchError(f"Could not fetch that URL: {exc}") from exc
    finally:
        client.close()
