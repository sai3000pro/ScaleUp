"""Health surfaces are offline-testable and never leak credentials."""

from __future__ import annotations

import json

from app.llm.factory import LLM_PROVIDERS
from app.main import app
from app.services import health_service

OPENAPI = app.openapi()


# @spec OPS-INTEG-001, OPS-INTEG-003
def test_providers_reports_what_is_selected() -> None:
    result = health_service.provider_report()

    selected = result["selected"]
    assert selected["llm"] in set(LLM_PROVIDERS)
    assert selected["voice"] in {"fake", "elevenlabs"}
    assert selected["email"] in {"fake", "resend"}
    assert selected["storage"] in {"local", "gcs"}
    assert isinstance(result["deployed"], bool)
    assert isinstance(result["all_ready"], bool)


# @spec OPS-INTEG-004, OPS-INTEG-005
def test_providers_names_every_integration_and_how_to_enable_it() -> None:
    result = health_service.provider_report()
    by_key = {item["key"]: item for item in result["integrations"]}

    assert {"anthropic", "openai", "elevenlabs", "exa", "resend", "gcs", "google_oauth"} <= set(by_key)
    assert {"n8n_inbound", "n8n_outbound"} <= set(by_key)
    for item in result["integrations"]:
        assert item["mode"] in {"off", "live", "misconfigured"}
        # Someone reading "off" needs to know what turning it on takes, and
        # what they are getting instead in the meantime.
        assert item["enable_hint"]
        assert item["fallback"]


# @spec OPS-HEALTH-004, OPS-INTEG-005
def test_providers_never_exposes_a_credential_value(monkeypatch) -> None:
    """Names, not values.

    The earlier version asserted the substring "key" never appeared, which
    stopped being a useful signal once the response began naming the variables
    an operator has to set: ELEVENLABS_API_KEY is a name, not a secret. Planting
    a known value and asserting its absence tests the thing that matters.
    """
    planted = "sk-planted-credential-value"
    settings = health_service.get_settings()
    monkeypatch.setattr(settings, "elevenlabs_api_key", planted, raising=False)
    monkeypatch.setattr(settings, "voice_provider", "elevenlabs", raising=False)

    payload = json.dumps(health_service.provider_report())
    assert planted not in payload
    # The NAME is expected to be present; that is how anyone knows what to set.
    assert "ELEVENLABS_API_KEY" in payload


# @spec OPS-HEALTH-001
def test_providers_and_ready_routes_are_registered() -> None:
    assert "/api/health/providers" in OPENAPI["paths"]
    assert "/api/health/ready" in OPENAPI["paths"]
    assert "/api/health/live" in OPENAPI["paths"]
