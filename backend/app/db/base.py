"""Declarative base and shared column types.

The naming convention is not optional. Without it, Alembic autogenerate emits
unnamed CHECK and UNIQUE constraints, and a later migration that needs to drop
one has nothing to name -- the classic way an Alembic history becomes
un-downgradable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Every `Mapped[datetime]` becomes `timestamptz`, not the SQLAlchemy default
    # of TIMESTAMP WITHOUT TIME ZONE.
    #
    # This is load-bearing rather than cosmetic. The whole product is built on
    # comparing `due_at` to now and measuring how overdue something is; naive
    # timestamps make that arithmetic wrong across DST and across any user not
    # in the server's zone, and asyncpg rejects a tz-aware value for a naive
    # column outright rather than corrupting it quietly.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), default=utcnow)
