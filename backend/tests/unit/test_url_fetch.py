"""The URL guard.

**Nothing here touches the network, and nothing here monkeypatches
`socket.getaddrinfo` globally.** The resolver and the transport are both
injected: a global patch would have been shorter and would also have broken
every Postgres connection the integration suite opens in the same session.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from app.config import get_settings
from app.ingestion.fetch import UrlFetchError, assert_public_url, fetch_url

PUBLIC = "93.184.216.34"


def resolver_for(*addresses: str):
    """A `getaddrinfo` that answers with exactly these addresses."""

    def resolve(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


def refusing_resolver(host, port, *args, **kwargs):
    raise socket.gaierror(-2, "Name or service not known")


PUBLIC_RESOLVER = resolver_for(PUBLIC)


# ── the address table ─────────────────────────────────────────────────────
#
# Each row is a shape that has been used as a real bypass somewhere. The two
# that matter most are the IPv6-mapped metadata address, which is not private to
# a naive v6 test and is the metadata endpoint to the kernel, and the mixed
# record set, where accepting a host because ONE answer is public hands the
# attacker the choice of which one the connection uses.

REFUSED_ADDRESSES = [
    ("169.254.169.254", "cloud metadata, the actual objective"),
    ("::ffff:169.254.169.254", "the same, IPv4-mapped into IPv6"),
    ("2002:a9fe:a9fe::1", "the same, 6to4-encoded"),
    ("127.0.0.1", "loopback"),
    ("::1", "loopback, v6"),
    ("10.1.2.3", "RFC1918"),
    ("172.16.5.4", "RFC1918"),
    ("192.168.1.1", "RFC1918, the home router admin page"),
    ("100.64.0.1", "carrier-grade NAT"),
    ("0.0.0.0", "unspecified, which many stacks route to localhost"),
    ("fd00::1", "unique local, v6"),
    ("fe80::1", "link local, v6"),
    ("224.0.0.1", "multicast"),
    ("192.0.2.1", "TEST-NET-1, reserved"),
]


@pytest.mark.parametrize("address,why", REFUSED_ADDRESSES)
def test_a_host_resolving_to_a_private_address_is_refused(address: str, why: str) -> None:
    with pytest.raises(UrlFetchError, match="private or reserved"):
        assert_public_url("http://totally-public.example.com/x", resolver=resolver_for(address))


def test_a_mixed_record_set_is_refused() -> None:
    """One public answer does not launder the private one.

    The attacker owns the record set, so "at least one address is public" gives
    them the choice of which address the connection actually uses.
    """
    with pytest.raises(UrlFetchError, match="private or reserved"):
        assert_public_url("http://mixed.example.com/", resolver=resolver_for(PUBLIC, "169.254.169.254"))


def test_a_public_address_is_allowed() -> None:
    assert assert_public_url("https://example.com/article", resolver=PUBLIC_RESOLVER)
    assert assert_public_url("http://example.com:80/a", resolver=PUBLIC_RESOLVER)
    assert assert_public_url("https://example.com:443/a", resolver=resolver_for("2606:2800:220:1::1"))


# ── the URL table ─────────────────────────────────────────────────────────

REFUSED_URLS = [
    ("file:///etc/passwd", "Only http and https", "a local file"),
    ("file://C:/Windows/win.ini", "Only http and https", "a local file, Windows"),
    ("gopher://example.com/x", "Only http and https", "gopher, the classic smuggler"),
    ("redis://localhost:6380/0", "Only http and https", "our own broker's scheme"),
    ("ftp://example.com/x", "Only http and https", "ftp"),
    ("data:text/html,<h1>x", "Only http and https", "an inline payload"),
    ("javascript:alert(1)", "Only http and https", "not a fetchable thing at all"),
    ("//example.com/x", "Only http and https", "scheme-relative"),
    ("http://user:pass@example.com/", "credentials", "credential smuggling"),
    ("http://user@example.com/", "credentials", "credential smuggling, no password"),
    ("http://example.com:5433/", "ports 80 and 443", "the internal Postgres port"),
    ("http://example.com:7687/", "ports 80 and 443", "the internal Neo4j bolt port"),
    ("http://example.com:8000/", "ports 80 and 443", "our own API"),
    ("http://example.com:22/", "ports 80 and 443", "ssh"),
    ("https://", "no host", "no host at all"),
    ("http:///path", "no host", "empty host"),
]


@pytest.mark.parametrize("url,message,why", REFUSED_URLS)
def test_refused_urls(url: str, message: str, why: str) -> None:
    with pytest.raises(UrlFetchError, match=message):
        assert_public_url(url, resolver=PUBLIC_RESOLVER)


def test_an_unresolvable_host_is_refused_not_crashed() -> None:
    with pytest.raises(UrlFetchError, match="Could not resolve"):
        assert_public_url("http://nx.example.com/", resolver=refusing_resolver)


def test_a_literal_private_ip_in_the_url_is_refused() -> None:
    """The resolver returns the literal unchanged, so the range check catches it."""
    with pytest.raises(UrlFetchError, match="private or reserved"):
        assert_public_url("http://169.254.169.254/latest/meta-data/", resolver=resolver_for("169.254.169.254"))


# ── redirects ─────────────────────────────────────────────────────────────


def transport_from(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            raise AssertionError(f"unexpected request to {key}")
        return routes[key]

    return httpx.MockTransport(handler)


PAGE = b"<!doctype html><html><body><main><h1>Real</h1><p>Body text.</p></main></body></html>"


def test_a_redirect_to_the_metadata_endpoint_is_refused() -> None:
    """**The attack this whole module is shaped around.**

    The submitted URL is an ordinary public host and passes every check. The
    redirect it answers with is the payload -- so the checks have to run again,
    on the hop, or they were a check of the first URL only.
    """
    transport = transport_from(
        {
            "https://blog.example.com/post": httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        }
    )

    def resolve(host, port, *args, **kwargs):
        return resolver_for("169.254.169.254" if host == "169.254.169.254" else PUBLIC)(host, port)

    with pytest.raises(UrlFetchError, match="private or reserved"):
        fetch_url("https://blog.example.com/post", transport=transport, resolver=resolve)


def test_a_redirect_to_a_forbidden_scheme_is_refused() -> None:
    transport = transport_from(
        {"https://a.example.com/": httpx.Response(301, headers={"location": "file:///etc/passwd"})}
    )
    with pytest.raises(UrlFetchError, match="Only http and https"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_a_redirect_to_a_forbidden_port_is_refused() -> None:
    transport = transport_from(
        {"https://a.example.com/": httpx.Response(302, headers={"location": "http://a.example.com:6380/"})}
    )
    with pytest.raises(UrlFetchError, match="ports 80 and 443"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_a_relative_redirect_is_resolved_and_followed() -> None:
    transport = transport_from(
        {
            "https://a.example.com/old": httpx.Response(301, headers={"location": "/new"}),
            "https://a.example.com/new": httpx.Response(200, content=PAGE),
        }
    )
    fetched = fetch_url("https://a.example.com/old", transport=transport, resolver=PUBLIC_RESOLVER)
    assert fetched.url == "https://a.example.com/new"
    assert fetched.payload == PAGE


def test_a_redirect_loop_terminates() -> None:
    transport = transport_from(
        {
            "https://a.example.com/1": httpx.Response(302, headers={"location": "/2"}),
            "https://a.example.com/2": httpx.Response(302, headers={"location": "/1"}),
        }
    )
    with pytest.raises(UrlFetchError, match="redirected more than"):
        fetch_url("https://a.example.com/1", transport=transport, resolver=PUBLIC_RESOLVER)


# ── body handling ─────────────────────────────────────────────────────────


def test_an_oversized_body_is_refused_by_the_declared_length() -> None:
    cap = get_settings().url_fetch_max_bytes
    transport = transport_from(
        {
            "https://a.example.com/": httpx.Response(
                200, content=b"x" * 10, headers={"content-length": str(cap + 1)}
            )
        }
    )
    with pytest.raises(UrlFetchError, match="larger than"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_an_oversized_body_is_refused_even_when_the_length_lies() -> None:
    """Content-Length is the courtesy; the streaming cap is the limit."""
    cap = get_settings().url_fetch_max_bytes
    transport = transport_from(
        {
            "https://a.example.com/": httpx.Response(
                200, content=b"x" * (cap + 1024), headers={"content-length": "10"}
            )
        }
    )
    with pytest.raises(UrlFetchError, match="larger than"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_an_error_status_is_reported_not_ingested() -> None:
    transport = transport_from({"https://a.example.com/": httpx.Response(404, content=b"nope")})
    with pytest.raises(UrlFetchError, match="HTTP 404"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_an_empty_body_is_refused() -> None:
    transport = transport_from({"https://a.example.com/": httpx.Response(200, content=b"")})
    with pytest.raises(UrlFetchError, match="empty"):
        fetch_url("https://a.example.com/", transport=transport, resolver=PUBLIC_RESOLVER)


def test_a_transport_failure_becomes_a_url_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(UrlFetchError, match="Could not fetch"):
        fetch_url(
            "https://a.example.com/", transport=httpx.MockTransport(handler), resolver=PUBLIC_RESOLVER
        )


def test_a_successful_fetch_returns_the_final_url_and_content_type() -> None:
    transport = transport_from(
        {"https://a.example.com/x": httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})}
    )
    fetched = fetch_url("https://a.example.com/x", transport=transport, resolver=PUBLIC_RESOLVER)
    assert fetched.url == "https://a.example.com/x"
    assert fetched.content_type == "text/html"
    assert fetched.payload == PAGE


# ── the escape hatch ──────────────────────────────────────────────────────


def test_allow_private_hosts_is_refused_when_deployed() -> None:
    """The one setting that turns the whole module off must not survive a deploy."""
    from app.config import Settings

    with pytest.raises(ValueError, match="URL_FETCH_ALLOW_PRIVATE_HOSTS"):
        Settings(
            deployed=True,
            jwt_secret="a-real-secret-generated-properly",
            dev_auth_enabled=False,
            url_fetch_allow_private_hosts=True,
        )


def test_allow_private_hosts_skips_the_address_check(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "url_fetch_allow_private_hosts", True)
    assert assert_public_url("http://localhost/docs", resolver=resolver_for("127.0.0.1"))
    # The cheap checks still apply -- this is an address exemption, not an
    # amnesty on schemes and ports.
    with pytest.raises(UrlFetchError, match="Only http and https"):
        assert_public_url("file:///etc/passwd", resolver=resolver_for("127.0.0.1"))
    with pytest.raises(UrlFetchError, match="ports 80 and 443"):
        assert_public_url("http://localhost:5433/", resolver=resolver_for("127.0.0.1"))
