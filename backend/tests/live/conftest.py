"""The opt-in live gate: every test in this directory talks to a real provider.

Collected and skipped by default -- each test needs the credential its
provider requires, read from the environment, and skips rather than fails
without it -- and excluded from CI by marker, so the suite stays runnable with
no keys and no spend. Run it deliberately, with keys in the environment:

    GEMINI_API_KEY=... ELEVENLABS_API_KEY=... pytest tests/live -m live -q

Settings are built from overrides alone (`_env_file=None`), so a developer's
`.env` cannot select a provider the test did not ask for, and the root
conftest's `LLM_PROVIDER=fake` is overridden only through the patched
`get_settings` the provider modules read.
"""

from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.llm import factory, gemini_provider
from app.services import voice


# @spec LLM-LIVE-001
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/live" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.live)


def _key(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} is not set; the live gate needs the real credential")
    return value


@pytest.fixture
def gemini_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        embedding_provider="gemini",
        gemini_api_key=_key("GEMINI_API_KEY"),
    )
    monkeypatch.setattr(gemini_provider, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    factory.get_llm_client.cache_clear()
    yield settings
    factory.get_llm_client.cache_clear()


@pytest.fixture
def elevenlabs_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        _env_file=None,
        voice_provider="elevenlabs",
        elevenlabs_api_key=_key("ELEVENLABS_API_KEY"),
    )
    monkeypatch.setattr(voice, "get_settings", lambda: settings)
    return settings
