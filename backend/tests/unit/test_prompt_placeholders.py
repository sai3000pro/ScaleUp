"""Every prompt's placeholders must be in the syntax the renderer recognises.

This exists because of a failure that was invisible for as long as no real
provider was configured. `curriculum_plan/v1.md` wrote its variables as `{goal}`
while the renderer only substitutes `{{goal}}`. The renderer raises on a `{{var}}`
it cannot fill -- but a `{var}` is not a placeholder to it at all, so it passed the
text through untouched and reported success.

The deterministic provider computes its answer from the variables rather than from
the prompt text, so every test still passed. The first real call sent a model a
template containing the literal words `{goal}` and `{instrument}`, and got back a
confident tree for an instrument nobody asked about.

A regex over the prompt corpus is the whole fix: the mistake is mechanical, so the
check should be too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROMPTS = Path(__file__).resolve().parents[2] / "app" / "prompts"

#: A bare identifier in single braces. JSON examples inside prompts open braces
#: before a newline or a quote, never before an identifier and a closing brace, so
#: this does not fire on them.
SINGLE_BRACE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})")

#: What the renderer actually substitutes. Kept as a literal rather than imported,
#: so a change to the renderer's syntax has to be made deliberately in two places.
DOUBLE_BRACE = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")


def _referenced() -> list[Path]:
    """The prompt files a role can actually send.

    Superseded versions stay on disk -- an `llm_calls` row records a
    `prompt_sha256`, and a version deleted from the store makes that hash
    unresolvable -- but they are not held to this rule, because nothing can reach
    them. Repointing a role at one brings it back into scope automatically.
    """
    from app.llm.registry import ROLES

    return sorted({PROMPTS / config.prompt_id / f"{config.prompt_version}.md" for config in ROLES.values()})


PROMPT_FILES = _referenced()


def test_every_referenced_prompt_exists() -> None:
    """A role pointing at a missing file would make every check below vacuous."""
    assert len(PROMPT_FILES) > 10
    for path in PROMPT_FILES:
        assert path.is_file(), f"{path.parent.name}/{path.name} is named by a role and not on disk"


# @spec LLM-PROMPT-005
@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_no_prompt_uses_a_placeholder_the_renderer_ignores(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    stray = SINGLE_BRACE.findall(text)
    assert not stray, (
        f"{path.parent.name}/{path.name} writes {stray} in single braces. The renderer only "
        "substitutes {{name}}, and passes anything else through to the model verbatim."
    )


# @spec LLM-PROMPT-005
@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_prompt_takes_at_least_one_variable(path: Path) -> None:
    """A prompt with no placeholder at all is the same failure, fully collapsed."""
    text = path.read_text(encoding="utf-8")
    assert DOUBLE_BRACE.search(text), f"{path.parent.name}/{path.name} interpolates nothing"
