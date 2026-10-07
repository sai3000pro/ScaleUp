"""Superseded prompt files are identifiable from the store."""

from __future__ import annotations

from app.llm.registry import live_prompt_versions, superseded_prompt_versions
from app.prompts.registry import PROMPTS_DIR


# @spec LLM-PROMPT-004
def test_the_superseded_set_is_exactly_the_dead_versions() -> None:
    assert set(superseded_prompt_versions()) == {
        ("curriculum_plan", "v1"),
        ("performance_feedback", "v1"),
        ("question_gen", "v1"),
        ("question_gen", "v2"),
    }


# @spec LLM-PROMPT-004
def test_every_live_version_exists_on_disk() -> None:
    for prompt_id, version in live_prompt_versions().items():
        assert (PROMPTS_DIR / prompt_id / f"{version}.md").is_file(), f"{prompt_id}/{version}"
