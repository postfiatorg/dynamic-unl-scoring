"""Cancellation-safe completion of synchronous background work."""
import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

_WorkerResult = TypeVar("_WorkerResult")


async def run_worker_to_completion(work: Callable[[], _WorkerResult]) -> _WorkerResult:
    """Keep the caller's session lock until a synchronous worker has stopped.

    Cancelling to_thread's await does not stop its thread. Shield and drain
    the worker before propagating cancellation, including repeated shutdown
    cancellation, so the caller's finally block cannot unlock early.
    """
    worker = asyncio.create_task(asyncio.to_thread(work))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        try:
            worker.result()
        except Exception:
            logger.exception("Background worker failed while cancellation was draining")
        raise


