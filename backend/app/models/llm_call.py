"""One row per LLM call, including failures.

`prompt_sha256` is the column that makes this table worth having. When grading
quality shifts after a prompt edit, "which exact bytes produced this grade?" is
the question you need answered, and it cannot be backfilled. One column now.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','schema_error','provider_error','timeout','refusal','cancelled')",
            name="status_valid",
        ),
        Index("ix_llm_calls_fingerprint", "request_fingerprint"),
        Index("ix_llm_calls_course_role", "course_id", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Callers name a role, never a model. The role -> model mapping lives in
    # app/llm/registry.py and is what keeps a textbook ingest at cents.
    role: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))

    prompt_id: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    prompt_sha256: Mapped[str] = mapped_column(String(64))

    # sha256(prompt_sha || model || rendered_input). Enables a response cache,
    # which is worth real money when you re-run a 120-call extraction after
    # fixing a bug in the reducer.
    request_fingerprint: Mapped[str] = mapped_column(String(64))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
