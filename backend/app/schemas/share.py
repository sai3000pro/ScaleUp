from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ShareCreated(BaseModel):
    """The owner-facing answer to \"share this course\".

    `url` is the one place the raw token ever appears in an API response. The
    backend stores only its SHA-256, so a later GET cannot re-show it -- the
    owner copies it now or creates a fresh share (rotating the old token).
    """

    course_id: uuid.UUID
    url: str
    created_at: datetime


class ShareStatus(BaseModel):
    course_id: uuid.UUID
    shared: bool
    # When the share was created; null when `shared` is false. The raw link is
    # deliberately not returned -- only its hash is stored.
    created_at: datetime | None


class SharePreview(BaseModel):
    """What an anonymous visitor learns from a share link.

    Deliberately small: title, shape, and who shared it. Documents, chunks, the
    graph, and questions stay behind the owner's account; the visitor decides to
    copy based on what the tree looks like, not on its raw material.
    """

    model_config = ConfigDict(from_attributes=True)

    course_id: uuid.UUID
    title: str
    description: str | None
    status: str
    node_count: int
    edge_count: int
    shared_by: str
    created_at: datetime
