"""Transactional email boundary for account recovery.

The auth service only constructs a reset URL and calls this module. Keeping the
provider here makes Resend replaceable and keeps provider credentials out of
routers, tasks, and tests.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_password_reset_email(email: str, display_name: str, reset_url: str) -> None:
    settings = get_settings()
    subject = "Reset your ScaleUp password"
    text = (
        f"Hi {display_name},\n\n"
        f"Reset your ScaleUp password here:\n{reset_url}\n\n"
        "This link expires soon and can only be used once. If you did not request "
        "a reset, you can ignore this email."
    )

    if settings.email_provider == "fake":
        # Deliberately visible only in local logs: the API response stays
        # enumeration-safe and never returns a reset token to the browser.
        logger.info("fake password reset email for %s: %s", email, reset_url)
    elif settings.email_provider == "resend":
        if not settings.resend_api_key:
            raise RuntimeError("RESEND_API_KEY is required when EMAIL_PROVIDER=resend")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [email], "subject": subject, "text": text},
            )
        response.raise_for_status()
    else:
        raise RuntimeError(f"Unsupported email provider: {settings.email_provider}")
