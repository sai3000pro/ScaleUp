"""Shared machinery every provider uses: render, fingerprint, validate.

Kept out of the providers so that "what the contract is" and "how a vendor is
called" stay separate concerns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.llm.base import LLMRole, SchemaValidationError
from app.llm.registry import ROLES, RoleConfig
from app.prompts.registry import load_prompt, load_schema


@dataclass(frozen=True, slots=True)
class PreparedCall:
    role: LLMRole
    config: RoleConfig
    prompt_text: str
    prompt_sha256: str
    schema: dict[str, Any]
    request_fingerprint: str


def prepare(role: LLMRole, variables: Mapping[str, Any], model: str) -> PreparedCall:
    config = ROLES[role]
    prompt = load_prompt(config.prompt_id, config.prompt_version)
    schema = load_schema(config.schema_id, config.schema_version)
    rendered = prompt.render(variables)

    # Identifies this exact request. Enables a response cache, which is worth
    # real money when re-running a 120-call extraction after fixing a reducer bug.
    fingerprint = hashlib.sha256(f"{prompt.sha256}|{model}|{rendered}".encode("utf-8")).hexdigest()

    return PreparedCall(
        role=role,
        config=config,
        prompt_text=rendered,
        prompt_sha256=prompt.sha256,
        schema=schema,
        request_fingerprint=fingerprint,
    )


def validate_or_raise(data: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Validate against the role's JSON schema.

    Raising rather than returning a best-effort object is the point of the seam:
    a caller that has to re-check the shape gains nothing from it.
    """
    if not isinstance(data, dict):
        raise SchemaValidationError(f"expected a JSON object, got {type(data).__name__}")

    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        detail = "; ".join(f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors[:5])
        raise SchemaValidationError(detail)

    return data


def parse_json_or_raise(text: str) -> Any:
    """Tolerate a fenced code block, which models still emit occasionally."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -len("```")]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"response was not valid JSON: {exc}") from exc
