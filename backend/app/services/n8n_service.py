"""Outbound events to n8n.

The inbound direction already existed: n8n calls the app, the app verifies an
HMAC signature and answers idempotently. This is the other half -- the app
telling n8n that something happened, so a workflow can react to a finished take
instead of polling for one.

Three properties, in order of how much they matter:

**Off by default and genuinely inert.** With `N8N_WEBHOOK_URL` empty nothing is
constructed, nothing is scheduled, and no code path waits. Emitting is not
"send to a stub"; it is a function that returns immediately.

**It can never affect a take.** Every failure -- unreachable host, timeout, 500,
DNS -- is swallowed and logged. A learner's score, EXP, and feedback are already
committed before an event is emitted, and an automation platform being down is
not a reason for practice to fail.

**Signed with the same secret, the same way.** Reusing `sign_payload` over the
exact bytes sent means the outbound signature is verifiable by the same recipe
the inbound direction documents, and there is one implementation to get right.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app.config import get_settings
from app.services.webhook_service import sign_payload

logger = logging.getLogger(__name__)

__all__ = ["EVENT_TYPES", "emit", "enabled"]

# The events the app knows how to announce. Adding one is adding a constant
# here and a call site; n8n decides whether it cares.
EVENT_TYPES = (
    "attempt.completed",
    "node.unlocked",
    "curriculum.published",
)


def enabled() -> bool:
    return bool(get_settings().n8n_webhook_url)


# @spec OPS-HOOK-006, OPS-HOOK-007, OPS-HOOK-008, OPS-HOOK-009, OPS-HOOK-010
async def emit(event_type: str, payload: Mapping[str, Any], *, correlation_id: str | None = None) -> bool:
    """Announce one event. Returns whether it was delivered.

    The return value is for tests and for a caller that wants to log; no caller
    should branch on it in a way that changes what the learner sees.
    """
    settings = get_settings()
    if not settings.n8n_webhook_url:
        return False
    if event_type not in EVENT_TYPES:
        # A typo'd event name would otherwise be a silent no-op on the n8n side,
        # discovered weeks later as "the workflow never fires".
        logger.warning("refusing to emit unknown n8n event type %r", event_type)
        return False

    body = json.dumps(
        {
            "event_type": event_type,
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": dict(payload),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    headers = {"Content-Type": "application/json", "X-Event-Type": event_type}
    if settings.webhook_secret:
        # Signed over the exact bytes sent. Serializing once and signing that
        # same string is what stops a pretty-printer from silently invalidating
        # every signature.
        headers["X-Webhook-Signature"] = sign_payload(settings.webhook_secret, body)

    try:
        async with httpx.AsyncClient(timeout=settings.n8n_timeout_seconds) as client:
            response = await client.post(settings.n8n_webhook_url, content=body, headers=headers)
        if response.status_code >= 400:
            logger.warning("n8n rejected %s with %s", event_type, response.status_code)
            return False
    except Exception as exc:  # noqa: BLE001 - automation being down is not a practice failure
        logger.warning("could not emit %s to n8n: %s", event_type, exc)
        return False
    return True
