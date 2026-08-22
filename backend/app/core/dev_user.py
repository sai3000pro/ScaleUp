"""Identity of the seeded development user, in one place.

Split out of `app.seed` so that `app.services.auth_service` can provision this
user on demand without importing the seed module, which imports
`app.services.graph_service` and would close an import cycle.

`app.seed` re-exports these names, so `from app.seed import DEV_USER_ID` keeps
working for the tests and scripts that already use it.
"""

from __future__ import annotations

import uuid

# Fixed so the ids are copy-pasteable and re-seeding is idempotent.
DEV_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

DEV_EMAIL = "dev@example.com"
DEV_PASSWORD = "devpassword123"  # noqa: S105 -- local dev account, never a real credential
DEV_DISPLAY_NAME = "Dev"
