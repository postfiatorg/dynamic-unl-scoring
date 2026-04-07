"""Tests for the scoring round scheduler."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.services.scheduler import (
    ADVISORY_LOCK_ID,
    _is_round_due,
    _release_lock,
    _try_acquire_lock,
    scheduler_loop,
)


def _patch_scheduler_settings(mock_settings):
    """Set default scheduler settings on a mock."""
    mock_settings.scoring_cadence_hours = 168
    mock_settings.scheduler_check_interval_seconds = 3600
    mock_settings.scheduler_startup_delay_seconds = 0


# ---------------------------------------------------------------------------
# _is_round_due
# ---------------------------------------------------------------------------


class TestIsRoundDue:
    @patch("scoring_service.services.scheduler.settings")
    def test_due_when_no_previous_rounds(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        assert _is_round_due(conn) is True

    @patch("scoring_service.services.scheduler.settings")
    def test_due_when_cadence_elapsed(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        last_completed = datetime.now(timezone.utc) - timedelta(hours=200)
        cursor.fetchone.return_value = (last_completed,)

        assert _is_round_due(conn) is True

    @patch("scoring_service.services.scheduler.settings")
    def test_not_due_when_cadence_not_elapsed(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        last_completed = datetime.now(timezone.utc) - timedelta(hours=100)
        cursor.fetchone.return_value = (last_completed,)

        assert _is_round_due(conn) is False

    @patch("scoring_service.services.scheduler.settings")
    def test_due_at_exact_cadence(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        last_completed = datetime.now(timezone.utc) - timedelta(hours=168)
        cursor.fetchone.return_value = (last_completed,)

        assert _is_round_due(conn) is True


# ---------------------------------------------------------------------------
# Advisory lock
# ---------------------------------------------------------------------------


class TestAdvisoryLock:
    def test_acquire_returns_true_when_available(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (True,)

        assert _try_acquire_lock(conn) is True
        sql = cursor.execute.call_args[0][0]
        assert "pg_try_advisory_lock" in sql

    def test_acquire_returns_false_when_held(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (False,)

        assert _try_acquire_lock(conn) is False

    def test_acquire_uses_correct_lock_id(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (True,)

        _try_acquire_lock(conn)
        params = cursor.execute.call_args[0][1]
        assert params == (ADVISORY_LOCK_ID,)

    def test_release_calls_advisory_unlock(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        _release_lock(conn)
        sql = cursor.execute.call_args[0][0]
        assert "pg_advisory_unlock" in sql


# ---------------------------------------------------------------------------
# scheduler_loop
# ---------------------------------------------------------------------------


class TestSchedulerLoop:
    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_triggers_round_when_due(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due, mock_get_db,
    ):
        _patch_scheduler_settings(mock_settings)
        mock_get_db.return_value = MagicMock()
        mock_due.return_value = True
        mock_lock.return_value = True

        call_count = 0
        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        mock_orchestrator = MagicMock()
        mock_orchestrator.run_round.return_value = {"status": "COMPLETE", "round_number": 1}

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_orchestrator.run_round.assert_called_once()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_skips_when_not_due(
        self, mock_settings, mock_sleep, mock_due, mock_get_db,
    ):
        _patch_scheduler_settings(mock_settings)
        mock_get_db.return_value = MagicMock()
        mock_due.return_value = False

        call_count = 0
        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        mock_orchestrator = MagicMock()

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_orchestrator.run_round.assert_not_called()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_skips_when_lock_held(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due, mock_get_db,
    ):
        _patch_scheduler_settings(mock_settings)
        mock_get_db.return_value = MagicMock()
        mock_due.return_value = True
        mock_lock.return_value = False

        call_count = 0
        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        mock_orchestrator = MagicMock()

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_orchestrator.run_round.assert_not_called()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_startup_delay_called(self, mock_settings, mock_sleep):
        mock_settings.scheduler_startup_delay_seconds = 300
        mock_settings.scheduler_check_interval_seconds = 3600
        mock_settings.scoring_cadence_hours = 168

        call_count = 0
        async def track_and_stop(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = track_and_stop

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop()

        first_sleep_arg = mock_sleep.call_args_list[0][0][0]
        assert first_sleep_arg == 300

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_releases_lock_after_round(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due, mock_get_db,
    ):
        _patch_scheduler_settings(mock_settings)
        mock_get_db.return_value = MagicMock()
        mock_due.return_value = True
        mock_lock.return_value = True

        call_count = 0
        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        mock_orchestrator = MagicMock()
        mock_orchestrator.run_round.return_value = {"status": "COMPLETE"}

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_release.assert_called()
