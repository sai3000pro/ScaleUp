"""Run a coroutine to completion from synchronous code, safely.

The providers are async (both vendor SDKs are); Celery tasks are sync. The naive
bridge is `asyncio.run(...)`, and it works right up until the caller is itself
inside a running loop -- which happens whenever a task executes eagerly inside an
async test, or an async request handler calls a pipeline stage directly. There
the failure is `RuntimeError: asyncio.run() cannot be called from a running event
loop`, thrown from deep inside the provider rather than anywhere near the cause.

This helper handles both cases, so callers never have to know which context they
are in.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

__all__ = ["run_sync"]


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop on this thread: the ordinary Celery-worker case.
        return asyncio.run(coro)

    # A loop is already running on this thread. Blocking on it would deadlock,
    # so hand the coroutine to a worker thread with a private loop and wait.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync-bridge") as pool:
        return pool.submit(asyncio.run, coro).result()
