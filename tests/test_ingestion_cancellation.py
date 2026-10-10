"""Offline cancellation tests with real workers and a simulated session lock."""
import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.services import convergence_ingestion as scheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_ingestion_cancellation_keeps_lock_until_worker_finishes(worker_fails):
    started = threading.Event()
    finish = threading.Event()
    order = []
    held = False

    def acquire(_conn):
        nonlocal held
        if held:
            return False
        held = True
        return True

    def release(_conn):
        nonlocal held
        order.append("release")
        held = False

    def work():
        started.set()
        if not finish.wait(5):
            raise AssertionError("test failed to release worker")
        order.append("worker_finished")
        if worker_fails:
            raise RuntimeError("synthetic worker failure")
        return {"decoded": 0}

    conn = MagicMock()
    conn.close.side_effect = lambda: order.append("close")
    client = MagicMock()
    client.publisher_address = "synthetic"
    with (
        patch.object(scheduler, "get_db", return_value=conn),
        patch.object(scheduler, "_try_acquire_lock", side_effect=acquire),
        patch.object(scheduler, "_release_lock", side_effect=release),
        patch.object(scheduler, "_run_pass_with_own_connection", side_effect=lambda *args: work()),
        patch.object(scheduler, "settings") as settings,
    ):
        settings.convergence_ingestion_enabled = True
        settings.pftl_enabled = True
        settings.convergence_ingestion_startup_delay_seconds = 0
        settings.convergence_ingestion_poll_interval_seconds = 60
        task = asyncio.create_task(scheduler.convergence_ingestion_loop(client))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            assert not task.done()
            assert not acquire(object()), "another scheduler must not acquire the lock"
            assert order == []
            task.cancel()  # repeated shutdown cancellation must not release early
            for _ in range(3):
                await asyncio.sleep(0)
            assert not task.done()
            assert order == []
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
        assert order == ["worker_finished", "release", "close"]
