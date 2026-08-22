"""Celery application and queue routing.

Three queues from day one, because the stages have very different concurrency
profiles: `ingest` is CPU/IO bound (PyMuPDF, chunking), `llm` is network bound
and rate limited, `graph` is a short serial reduce. Declaring them now costs
nothing and means scaling the LLM stage later is a worker flag rather than a
refactor.

On Windows the worker must run `--pool=solo` (see CLAUDE.md) -- prefork needs
fork(), which Windows lacks.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "learn_anything",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # A task module missing from here is never imported by the worker, so its
    # task never registers and every job of that kind sits `queued` at 0% with
    # nothing logged. `app.tasks.reindex` defines `ingest.run_reindex`, which the
    # `ingest.*` route below already covers.
    include=["app.tasks.ingest", "app.tasks.reindex"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Acknowledge only after the task finishes, so a worker killed mid-ingest
    # redelivers rather than silently dropping the job. Every task is written to
    # be idempotent precisely so this is safe.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Long tasks + late acks means a greedy prefetch would strand queued work
    # behind one slow worker.
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    # A decompression-bomb PDF, or a parser pathology, otherwise parks the
    # `--pool=solo` worker for ever -- and on Windows there is no second worker
    # to take over. The soft limit raises inside the task so the job row can be
    # marked failed; the hard limit is the backstop if it does not.
    task_soft_time_limit=45 * 60,
    task_time_limit=50 * 60,
    result_expires=60 * 60 * 24,
    task_default_queue="default",
    # One route, because there is one task. The four entries that used to sit
    # here (`ingest.extract_window`, `ingest.embed_batch`, `ingest.reduce_graph`,
    # `ingest.finalize`) named tasks that have never existed -- the pipeline runs
    # as a single `run_ingest_pipeline` -- so the `llm` and `graph` queues were
    # dead letterboxes and anyone debugging an idle one was chasing a phantom.
    task_routes={"ingest.*": {"queue": "ingest"}},
)
