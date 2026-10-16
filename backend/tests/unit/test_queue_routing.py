"""Queue routing is exercised, not assumed: every registered task resolves to a queue
the documented worker command consumes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.tasks import celery_app as celery_module

REPO_ROOT = Path(__file__).resolve().parents[3]
OPERATOR_DOCS = ("CLAUDE.md", "README.md", "docs/deployment.md", "docs/deployment-hosted.md")


def _routed_queue(task_name: str) -> str:
    app = celery_module.celery_app
    options = app.amqp.router.route({}, task_name)
    queue = options.get("queue")
    if queue is None:
        return app.conf.task_default_queue
    return queue if isinstance(queue, str) else queue.name


def _registered_tasks() -> list[str]:
    import app.tasks.ingest  # noqa: F401
    import app.tasks.reindex  # noqa: F401

    return sorted(name for name in celery_module.celery_app.tasks if not name.startswith("celery."))


def _documented_queue_lists() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for relative in OPERATOR_DOCS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for match in re.finditer(r"-Q ([a-z]+(?:,[a-z]+)+)\b", text):
            found.setdefault(relative, set()).update(match.group(1).split(","))
    return found


# @spec OPS-CI-006
def test_every_registered_task_routes_to_a_queue() -> None:
    tasks = _registered_tasks()
    assert tasks, "no application tasks registered"
    for task_name in tasks:
        assert _routed_queue(task_name) == "ingest", task_name


# @spec OPS-CI-006
def test_default_queue_catches_unrouted_tasks() -> None:
    assert _routed_queue("unrouted.task") == "default"


# @spec OPS-CI-006
@pytest.mark.parametrize("document", OPERATOR_DOCS)
def test_operator_queue_list_matches_routing(document: str) -> None:
    routed = {_routed_queue(name) for name in _registered_tasks()} | {celery_module.celery_app.conf.task_default_queue}
    documented = _documented_queue_lists().get(document)
    assert documented is not None, f"{document} does not tell the operator which queues to consume"
    assert documented == routed, f"{document} names queues {documented ^ routed} that routing disagrees with"
