"""Prompts and JSON schemas as versioned, hashed artifacts.

Every prompt is loaded once at import and hashed. `llm_calls.prompt_sha256`
records which exact bytes produced each result -- without it, "did grading get
worse after I edited the rubric?" is unanswerable retroactively, and it cannot be
backfilled.

A new prompt version is a NEW FILE (`v2.md`), never an edit to `v1.md`.
`test_prompt_versions_are_frozen` pins the hashes so an accidental edit fails
loudly instead of silently invalidating every historical row.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

PROMPTS_DIR = Path(__file__).resolve().parent
SCHEMAS_DIR = PROMPTS_DIR.parent / "llm" / "json_schemas"

# `{{name}}` — a placeholder is a bare identifier, so it can never match user
# text like `{{0}}` or `{{ if x }}`.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass(frozen=True, slots=True)
class Prompt:
    prompt_id: str
    version: str
    text: str
    sha256: str

    def render(self, variables: Mapping[str, Any]) -> str:
        """Substitute `{{name}}` placeholders.

        Deliberately not Jinja: a prompt with logic in it is a prompt you cannot
        read as the model reads it, and every conditional doubles the number of
        variants you would have to evaluate.

        Single pass, over the TEMPLATE only. Substituting values one key at a
        time and then scanning the result for leftover `{{` cannot tell a
        genuinely missing variable from a brace the *user* wrote: an answer
        containing `int a{{0}};`, or a textbook page quoting Jinja or
        Handlebars, would raise `KeyError` and fail the call. Grading crashed on
        the learner's own text, and extraction dropped windows for the crime of
        containing C++.
        """
        missing: list[str] = []

        def substitute(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                missing.append(name)
                return match.group(0)
            return str(variables[name])

        rendered = PLACEHOLDER.sub(substitute, self.text)

        if missing:
            raise KeyError(
                f"unsubstituted placeholder in {self.prompt_id}/{self.version}: {sorted(set(missing))}"
            )

        return rendered


@lru_cache(maxsize=None)
# @spec LLM-PROMPT-001, LLM-PROMPT-002
def load_prompt(prompt_id: str, version: str = "v1") -> Prompt:
    path = PROMPTS_DIR / prompt_id / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt at {path}")

    # Read bytes and normalise newlines before hashing, so a git checkout with
    # different line endings does not change the recorded hash.
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Prompt(prompt_id=prompt_id, version=version, text=text, sha256=digest)


@lru_cache(maxsize=None)
def load_schema(schema_id: str, version: str = "v1") -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{schema_id}.{version}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no schema at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# @spec LLM-PROMPT-004
def available_prompts() -> list[tuple[str, str]]:
    """(prompt_id, version) for every prompt on disk."""
    found: list[tuple[str, str]] = []
    for directory in sorted(p for p in PROMPTS_DIR.iterdir() if p.is_dir()):
        for markdown in sorted(directory.glob("v*.md")):
            found.append((directory.name, markdown.stem))
    return found
