"""Hosted mode: development defaults become startup refusals.

The security checks arm three ways -- a recognised platform variable,
HOSTED=true, or DEPLOYED=true -- and never inside CI.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.hosting import CI_SIGNALS, detect_hosting


@pytest.fixture(autouse=True)
def _not_running_inside_ci(monkeypatch) -> None:
    """These tests simulate hosted platforms; CI itself must not mask them."""
    for variable in CI_SIGNALS:
        monkeypatch.delenv(variable, raising=False)


def _settings(**overrides) -> Settings:
    """Settings built off no .env file, so the test is hermetic."""
    return Settings(_env_file=None, **overrides)


# @spec OPS-CONFIG-009
def test_a_recognised_platform_variable_is_detected(monkeypatch) -> None:
    monkeypatch.setenv("KOYEB_APP_NAME", "scaleup-api")
    signal = detect_hosting(__import__("os").environ.copy())
    assert signal is not None and signal.platform == "Koyeb"


def test_an_empty_platform_variable_detects_nothing(monkeypatch) -> None:
    monkeypatch.setenv("KOYEB_APP_NAME", "")
    assert detect_hosting(__import__("os").environ.copy()) is None


# @spec OPS-CONFIG-010
def test_a_platform_variable_inside_ci_detects_nothing(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("KOYEB_APP_NAME", "scaleup-api")
    assert detect_hosting(__import__("os").environ.copy()) is None


def test_nothing_detected_on_a_plain_environment() -> None:
    assert detect_hosting({}) is None


# @spec OPS-CONFIG-003, OPS-CONFIG-009, OPS-CONFIG-011
def test_hosted_refuses_a_placeholder_jwt_secret(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(ValueError) as caught:
        _settings()
    assert "RENDER (Render)" in str(caught.value)
    assert "JWT_SECRET" in str(caught.value)


# @spec OPS-CONFIG-003, OPS-CONFIG-008
def test_the_hosted_tier_does_not_demand_deployed_tier_integrations(monkeypatch) -> None:
    """Email fake, local storage and no Google OAuth are a supported hosted
    shape -- the security defaults are what may not stay."""
    monkeypatch.setenv("RENDER", "true")
    settings = _settings(
        jwt_secret="a-real-generated-secret",
        dev_auth_enabled=False,
        dev_webhooks_enabled=False,
        url_fetch_allow_private_hosts=False,
        cors_origin_regex=r"https://scaleup\.vercel\.app",
        email_provider="fake",
        storage_backend="local",
    )
    assert settings.is_hosted
    assert settings.hosting_signal == "RENDER (Render)"


# @spec OPS-CONFIG-008, OPS-CONFIG-011
def test_deployed_adds_the_durability_requirements(monkeypatch) -> None:
    with pytest.raises(ValueError) as caught:
        _settings(
            deployed=True,
            jwt_secret="a-real-generated-secret",
            dev_auth_enabled=False,
            dev_webhooks_enabled=False,
            url_fetch_allow_private_hosts=False,
            cors_origin_regex=r"https://scaleup\.vercel\.app",
            email_provider="fake",
        )
    assert "(DEPLOYED)" in str(caught.value)
    assert "EMAIL_PROVIDER" in str(caught.value)


# @spec OPS-CONFIG-003, OPS-CONFIG-011
def test_an_explicit_hosted_flag_names_itself(monkeypatch) -> None:
    with pytest.raises(ValueError) as caught:
        _settings(hosted=True, jwt_secret="a-real-generated-secret", dev_auth_enabled=True)
    assert "(HOSTED)" in str(caught.value)
    assert "DEV_AUTH_ENABLED" in str(caught.value)


# @spec OPS-CONFIG-008
def test_deployed_refuses_resend_without_a_key() -> None:
    with pytest.raises(ValueError) as caught:
        _settings(
            deployed=True,
            jwt_secret="a-real-generated-secret",
            dev_auth_enabled=False,
            dev_webhooks_enabled=False,
            url_fetch_allow_private_hosts=False,
            cors_origin_regex=r"https://scaleup\.vercel\.app",
            email_provider="resend",
            google_oauth_client_id="id",
            google_oauth_client_secret="secret",
            storage_backend="gcs",
            gcs_bucket="scaleup-uploads",
            webhook_secret="whsec",
        )
    assert "RESEND_API_KEY" in str(caught.value)


# @spec OPS-CONFIG-003
def test_unsigned_webhooks_are_refused_while_hosted(monkeypatch) -> None:
    with pytest.raises(ValueError) as caught:
        _settings(
            hosted=True,
            jwt_secret="a-real-generated-secret",
            dev_auth_enabled=False,
            dev_webhooks_enabled=True,
            url_fetch_allow_private_hosts=False,
            cors_origin_regex=r"https://scaleup\.vercel\.app",
        )
    assert "DEV_WEBHOOKS_ENABLED" in str(caught.value)


# @spec OPS-CONFIG-009
def test_hosting_signal_reports_detected_platform(monkeypatch) -> None:
    monkeypatch.setenv("FLY_APP_NAME", "scaleup")
    settings = _settings(
        jwt_secret="a-real-generated-secret",
        dev_auth_enabled=False,
        dev_webhooks_enabled=False,
        url_fetch_allow_private_hosts=False,
        cors_origin_regex=r"https://scaleup\.vercel\.app",
    )
    assert settings.hosting_signal == "FLY_APP_NAME (Fly.io)"


def test_hosting_signal_is_none_on_a_developer_machine() -> None:
    assert _settings().hosting_signal is None
