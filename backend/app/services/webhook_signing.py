"""Pure signing primitives shared by inbound and outbound webhook services."""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def sign_payload(secret: str, body: bytes) -> str:
    """The exact ``X-Webhook-Signature`` value for ``body`` under ``secret``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, provided: str | None) -> bool:
    """Constant-time comparison of the provided signature against the expected one."""
    if not provided or not provided.startswith(SIGNATURE_PREFIX):
        return False
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, provided)


def payload_sha256(body: bytes) -> str:
    """Hash raw request bytes for the webhook replay ledger."""
    return hashlib.sha256(body).hexdigest()
