from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / "n8n" / "workflows"


@pytest.mark.parametrize(
    "filename, signer_name, sender_name",
    [
        ("audio-retention-cleanup.json", "Sign cleanup request", "Expire audio older than 30 days"),
        ("nightly-quest-refresh.json", "Build payload", "Send webhook"),
    ],
)
def test_scheduled_webhooks_send_the_exact_string_used_for_hmac(
    filename: str, signer_name: str, sender_name: str
) -> None:
    workflow: dict[str, Any] = json.loads((WORKFLOWS / filename).read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    signer = nodes[signer_name]["parameters"]["jsCode"]
    sender = nodes[sender_name]["parameters"]

    assert "createHmac('sha256', SECRET).update(body).digest('hex')" in signer
    assert sender["contentType"] == "raw"
    assert sender["rawContentType"] == "application/json"
    assert sender["body"] == "={{ $json.body }}"
    assert "JSON.parse" not in signer
    assert workflow["active"] is False


def test_nightly_quest_template_emits_the_correlation_id_used_by_its_header() -> None:
    workflow = json.loads((WORKFLOWS / "nightly-quest-refresh.json").read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    signer = nodes["Build payload"]["parameters"]["jsCode"]
    headers = nodes["Send webhook"]["parameters"]["headerParameters"]["parameters"]

    assert "correlation_id: correlationId" in signer
    assert "return [{ json: { body, signature, correlation_id: correlationId } }];" in signer
    assert any(
        item["name"] == "X-Correlation-ID" and item["value"] == "={{ $json.correlation_id }}"
        for item in headers
    )


def test_audio_cleanup_template_has_a_daily_schedule_and_signed_headers() -> None:
    workflow = json.loads((WORKFLOWS / "audio-retention-cleanup.json").read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    request = nodes["Expire audio older than 30 days"]["parameters"]
    headers = request["headerParameters"]["parameters"]

    assert nodes["Daily schedule"]["type"] == "n8n-nodes-base.scheduleTrigger"
    assert any(item["name"] == "X-Webhook-Signature" and item["value"] == "={{ $json.signature }}" for item in headers)
    assert any(item["name"] == "X-Correlation-ID" for item in headers)
