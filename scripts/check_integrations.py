r"""What is wired up, what is running on a fallback, and what is misconfigured.

Answers "did my key take effect?" without starting the app, opening a browser,
or waiting for a Celery task to fail at 3am. Reports the presence of credentials
and never their values, so it is safe to run on a shared screen.

    cd backend
    .\.venv\Scripts\python.exe ..\scripts\check_integrations.py

Exits non-zero when something was asked for but is not configured -- so it works
as a pre-deploy gate in CI as well as a thing to eyeball.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.integrations import integration_statuses, missing_for_deployment  # noqa: E402

MARK = {"live": "[LIVE]", "off": "[ off]", "misconfigured": "[  ! ]"}


# @spec OPS-INTEG-006, OPS-INTEG-008
def main() -> int:
    settings = get_settings()
    statuses = integration_statuses(settings)

    print("\nExternal integrations\n")
    print(f"  {'':6} {'INTEGRATION':<24} {'DETAIL'}")
    print(f"  {'-' * 6} {'-' * 24} {'-' * 48}")

    for status in statuses:
        if status.mode == "live":
            detail = "configured and in use"
        elif status.mode == "misconfigured":
            detail = f"asked for, but {', '.join(status.missing)} is empty"
        else:
            detail = f"set {status.enable_hint}"
        print(f"  {MARK[status.mode]:6} {status.title:<24} {detail}")

    broken = [status for status in statuses if status.mode == "misconfigured"]
    if broken:
        print("\nMisconfigured -- these will fail at their first call, not at startup:\n")
        for status in broken:
            print(f"  {status.title}")
            print(f"    needs      {', '.join(status.missing)}")
            print(f"    get one at {status.provider_url}")

    off = [status for status in statuses if status.mode == "off"]
    if off:
        print("\nRunning on fallbacks. Each of these is a supported state:\n")
        for status in off:
            print(f"  {status.title:<24} {status.fallback}")

    print("\nTo turn one on: set the variables above in .env and restart the API")
    print("(and the Celery worker, which reads the same file).")

    if not settings.deployed:
        pending = missing_for_deployment(settings)
        if pending:
            print("\nBefore DEPLOYED=true, these must be live or startup will refuse:\n")
            for item in pending:
                print(f"  {item}")

    if broken:
        print(f"\n{len(broken)} integration(s) misconfigured.\n")
        return 1
    print("\nNothing is misconfigured. The app runs as-is.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
