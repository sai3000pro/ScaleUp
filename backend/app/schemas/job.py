from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Null for a `reindex` job, which spans every document in the course and so
    # has no single one to point at. The rest of the shape is unchanged, which is
    # what lets the existing polling UI serve both kinds with no new branch.
    document_id: uuid.UUID | None
    course_id: uuid.UUID
    state: str
    units_done: int
    units_total: int
    percent: float
    stage_detail: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
