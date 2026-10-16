"""Every constraint the code relies on is declared on the model, not only in a migration."""

from __future__ import annotations

from sqlalchemy import Index

from app.models import Course


# @spec OPS-MIGRATE-007
def test_course_copy_idempotency_index_is_declared_on_the_model() -> None:
    indexes = {index.name: index for index in Course.__table__.indexes if isinstance(index, Index)}
    index = indexes["uq_courses_owner_copy"]
    assert index.unique
    assert [column.name for column in index.columns] == ["owner_id", "copied_from_id"]
    assert "copied_from_id IS NOT NULL" in str(index.dialect_options["postgresql"]["where"])
