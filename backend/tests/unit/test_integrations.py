"""Turning an integration on must be configuration, never code.

These tests are the guarantee behind that claim: the registry answers "what is
on" honestly, the outbound emitter is genuinely inert when unconfigured, and no
path here can leak a credential's value.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from app.config import Settings
from app.integrations import INTEGRATIONS, integration_statuses, missing_for_deployment
from app.services import n8n_service


def _settings(**overrides) -> Settings:
    # `_env_file=None` so a developer's own .env cannot change the answer.
    return Settings(_env_file=None, **overrides)


class TestRegistry:
    def test_the_default_configuration_needs_no_credentials(self) -> None:
        for status in integration_statuses(_settings()):
            assert status.mode == "off"
            assert status.missing == ()

    def test_selecting_a_provider_without_its_key_is_misconfigured(self) -> None:
        statuses = {s.key: s for s in integration_statuses(_settings(voice_provider="elevenlabs"))}
        assert statuses["elevenlabs"].mode == "misconfigured"
        assert statuses["elevenlabs"].missing == ("ELEVENLABS_API_KEY",)
        assert statuses["elevenlabs"].ready is False

    def test_a_configured_provider_is_live(self) -> None:
        statuses = {
            s.key: s
            for s in integration_statuses(_settings(voice_provider="elevenlabs", elevenlabs_api_key="sk-not-real"))
        }
        assert statuses["elevenlabs"].mode == "live"
        assert statuses["elevenlabs"].missing == ()

    def test_an_unselected_integration_reports_nothing_missing(self) -> None:
        """An unset key on something nobody turned on is not a problem."""
        statuses = {s.key: s for s in integration_statuses(_settings())}
        assert statuses["exa"].missing == ()
        assert statuses["exa"].requires == ("EXA_API_KEY",)

    def test_google_oauth_needs_no_selector(self) -> None:
        half = {s.key: s for s in integration_statuses(_settings(google_oauth_client_id="id-only"))}
        assert half["google_oauth"].mode == "misconfigured"
        assert half["google_oauth"].missing == ("GOOGLE_OAUTH_CLIENT_SECRET",)

    def test_openai_covers_both_the_model_and_the_embedding_selector(self) -> None:
        for overrides in ({"llm_provider": "openai"}, {"embedding_provider": "openai"}):
            statuses = {s.key: s for s in integration_statuses(_settings(**overrides))}
            assert statuses["openai"].selected is True

    def test_deployment_requirements_are_listed_before_a_deploy(self) -> None:
        pending = missing_for_deployment(_settings())
        assert any("Resend" in item for item in pending)
        assert any("n8n (inbound)" in item for item in pending)

    @pytest.mark.parametrize("integration", INTEGRATIONS, ids=lambda item: item.key)
    def test_every_integration_describes_its_fallback(self, integration) -> None:
        """"Off" has to mean something specific, or nobody trusts the default."""
        assert integration.fallback
        assert integration.purpose
        assert integration.provider_url.startswith("https://")
        assert integration.credentials

    def test_no_status_field_can_carry_a_secret(self) -> None:
        secret = "sk-super-secret-value"
        statuses = integration_statuses(_settings(voice_provider="elevenlabs", elevenlabs_api_key=secret))
        assert secret not in json.dumps([asdict(status) for status in statuses], default=str)


class TestOutboundN8n:
    async def test_it_is_inert_when_unconfigured(self, monkeypatch) -> None:
        """Off means nothing is sent, not "sent to a stub"."""
        monkeypatch.setattr(n8n_service, "get_settings", lambda: _settings())
        assert n8n_service.enabled() is False
        assert await n8n_service.emit("attempt.completed", {"attempt_id": "x"}) is False

    async def test_an_unknown_event_type_is_refused(self, monkeypatch) -> None:
        """A typo'd event name would otherwise be discovered weeks later as
        "the workflow never fires"."""
        monkeypatch.setattr(
            n8n_service, "get_settings", lambda: _settings(n8n_webhook_url="https://n8n.example.com/hook")
        )
        assert await n8n_service.emit("attmept.completed", {}) is False

    async def test_a_delivery_failure_never_raises(self, monkeypatch) -> None:
        """An automation platform being down is not a practice failure."""
        monkeypatch.setattr(
            n8n_service,
            "get_settings",
            lambda: _settings(n8n_webhook_url="http://127.0.0.1:9/definitely-not-listening",
                              n8n_timeout_seconds=0.25),
        )
        assert await n8n_service.emit("attempt.completed", {"attempt_id": "x"}) is False

    async def test_a_delivered_event_is_signed_over_the_bytes_sent(self, monkeypatch) -> None:
        from app.services.webhook_service import verify_signature

        captured: dict[str, object] = {}

        class _Response:
            status_code = 200

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                return None

            async def post(self, url, content, headers):
                captured["url"] = url
                captured["body"] = content
                captured["headers"] = headers
                return _Response()

        monkeypatch.setattr(
            n8n_service,
            "get_settings",
            lambda: _settings(n8n_webhook_url="https://n8n.example.com/hook", webhook_secret="shared"),
        )
        monkeypatch.setattr(n8n_service.httpx, "AsyncClient", _Client)

        assert await n8n_service.emit("attempt.completed", {"attempt_id": "abc"}, correlation_id="corr-1") is True

        body = captured["body"]
        headers = captured["headers"]
        assert verify_signature("shared", body, headers["X-Webhook-Signature"])
        payload = json.loads(body)
        assert payload["event_type"] == "attempt.completed"
        assert payload["correlation_id"] == "corr-1"
        assert payload["payload"] == {"attempt_id": "abc"}

    async def test_it_sends_unsigned_when_no_secret_is_shared(self, monkeypatch) -> None:
        """Local n8n without a shared secret is a real setup, not an error."""
        captured: dict[str, object] = {}

        class _Response:
            status_code = 200

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                return None

            async def post(self, url, content, headers):
                captured["headers"] = headers
                return _Response()

        monkeypatch.setattr(
            n8n_service, "get_settings", lambda: _settings(n8n_webhook_url="https://n8n.example.com/hook")
        )
        monkeypatch.setattr(n8n_service.httpx, "AsyncClient", _Client)

        assert await n8n_service.emit("attempt.completed", {}) is True
        assert "X-Webhook-Signature" not in captured["headers"]


class TestBrowserDependencies:
    """The hosts the page reaches, which no credential controls.

    `INTEGRATIONS` means "a service an operator turns on by setting a key": every
    row is off by default and names its credentials, and the tests above enforce
    both. MediaPipe is neither -- there is no key, and it is reached whenever the
    camera is used -- so putting it in that table would have cost the table its
    meaning, while leaving it out left this product with one third-party
    dependency its own honesty surface could not answer for.
    """

    # @spec OPS-INTEG-007
    def test_every_host_the_browser_reaches_is_declared(self) -> None:
        from app.integrations import BROWSER_DEPENDENCIES

        assert BROWSER_DEPENDENCIES, "the camera path fetches from public CDNs; say so"
        for dependency in BROWSER_DEPENDENCIES:
            assert dependency.hosts, f"{dependency.title} names no host"
            assert dependency.fallback, f"{dependency.title} does not say what happens without it"
            assert dependency.reached_when, f"{dependency.title} does not say when it is contacted"
            assert dependency.provider_url.startswith("https://")

    # @spec OPS-INTEG-007
    def test_the_declared_hosts_are_the_ones_the_code_actually_fetches(self) -> None:
        """A register that drifts from the source is worse than none: it answers
        the audit question confidently and wrongly."""
        from pathlib import Path

        from app.integrations import BROWSER_DEPENDENCIES

        source = (
            Path(__file__).resolve().parents[3] / "frontend" / "lib" / "visualTracking.ts"
        ).read_text(encoding="utf-8")
        declared = {host for dependency in BROWSER_DEPENDENCIES for host in dependency.hosts}
        for host in declared:
            assert host in source, f"{host} is declared but visualTracking.ts no longer fetches from it"

    # @spec OPS-INTEG-005, OPS-INTEG-007
    def test_a_browser_dependency_names_no_credential(self) -> None:
        """If one ever needs a key it belongs in INTEGRATIONS, under the rules
        that table enforces -- off by default, and named credentials."""
        from app.integrations import BROWSER_DEPENDENCIES

        for dependency in BROWSER_DEPENDENCIES:
            assert all(
                option.startswith("NEXT_PUBLIC_") for option in dependency.options
            ), f"{dependency.title} names a server-side variable; it is an integration, not a browser dependency"
