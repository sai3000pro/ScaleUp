"""`.env.example` is the surface an operator configures the app through.

A setting that exists in `config.py` and appears nowhere in `.env.example` is
invisible: the only way to discover it is to read the source. That is exactly
the failure mode this file guards -- "I have the key, where does it go?" should
never require grepping Python.

Also asserts the inverse, because a stale key in the example file is worse than
a missing one: someone sets it, nothing happens, and the app looks broken.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.integrations import INTEGRATIONS

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
# Read by the Next.js app, not by pydantic, so it has no Settings field.
FRONTEND_KEYS = {"NEXT_PUBLIC_API_BASE_URL"}


def _documented() -> set[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))


def test_the_example_file_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} is the documented starting point and must exist"


# @spec OPS-CONFIG-005
def test_every_setting_is_documented() -> None:
    declared = {name.upper() for name in Settings.model_fields}
    missing = sorted(declared - _documented())
    assert not missing, f"add these to .env.example so they can be found without reading config.py: {missing}"


def test_no_stale_keys() -> None:
    declared = {name.upper() for name in Settings.model_fields}
    stale = sorted(_documented() - declared - FRONTEND_KEYS)
    assert not stale, f"these are in .env.example but no longer exist; setting them does nothing: {stale}"


@pytest.mark.parametrize("integration", INTEGRATIONS, ids=lambda item: item.key)
def test_every_integration_credential_is_documented(integration) -> None:
    """Naming a key in the integration table but not the example file is the
    exact gap that makes "plop the key in" require reading source."""
    documented = _documented()
    for name in integration.credentials + integration.options:
        assert name in documented, f"{integration.title} references {name}, which .env.example never mentions"


# @spec OPS-CONFIG-001
def test_every_integration_is_off_by_default() -> None:
    """The default configuration must need no credentials at all.

    This is the property that keeps CI free, keeps the demo runnable on a
    stranger's laptop, and keeps the fallbacks honest -- a fallback nobody
    exercises rots.
    """
    from app.integrations import integration_statuses

    for status in integration_statuses(Settings(_env_file=None)):
        assert status.mode == "off", f"{status.title} is not off in a default configuration"
