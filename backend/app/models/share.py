"""Share-token based course sharing.

The raw token is returned to the owner exactly once, when the share is created;
only its SHA-256 is stored, following the same rule as password-reset and
refresh tokens. A share has no expiry: revoking it deletes the row, which makes
the token worthless because the hash no longer exists to match.

One share per course, enforced by a unique constraint on `course_id`.
Re-creating a share rotates the token and silently invalidates the old one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseShare(Base):
    __tablename__ = "course_shares"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True, index=True
    )
    # sha256 hex of the raw token. The raw token is shown to the owner once and
    # never stored, so a database leak does not leak working share links.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
