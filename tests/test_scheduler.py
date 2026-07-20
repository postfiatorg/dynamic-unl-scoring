"""Tests for the scoring round scheduler."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.services.scheduler import (
    ADVISORY_LOCK_ID,
    _advance_schedule,
    _is_round_due,
    _release_lock,
    _try_acquire_lock,
    reanchor_schedule,
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


def _mock_conn(fetchone_results):
    """Build a MagicMock connection whose cursor yields the given fetchone results."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.side_effect = fetchone_results
    return conn, cursor


def _executed_sql(cursor):
    return [call[0][0] for call in cursor.execute.call_args_list]


class TestIsRoundDue:
    @patch("scoring_service.services.scheduler.settings")
    def test_due_when_schedule_in_past(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) - timedelta(hours=1)
        conn, cursor = _mock_conn([(next_due,)])

        assert _is_round_due(conn) is True
        assert len(cursor.execute.call_args_list) == 1

    @patch("scoring_service.services.scheduler.settings")
    def test_not_due_when_schedule_in_future(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) + timedelta(hours=1)
        conn, _ = _mock_conn([(next_due,)])

        assert _is_round_due(conn) is False

    @patch("scoring_service.services.scheduler.settings")
    def test_due_at_exact_boundary(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc)
        conn, _ = _mock_conn([(next_due,)])

        assert _is_round_due(conn) is True

    @patch("scoring_service.services.scheduler.settings")
    def test_no_seed_when_schedule_row_exists(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) + timedelta(hours=1)
        conn, cursor = _mock_conn([(next_due,)])

        _is_round_due(conn)

        assert not any("INSERT" in sql for sql in _executed_sql(cursor))

    @patch("scoring_service.services.scheduler.settings")
    def test_seeds_due_now_when_no_rounds(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn, cursor = _mock_conn([None, None])
        before = datetime.now(timezone.utc)

        assert _is_round_due(conn) is True

        insert_calls = [
            call for call in cursor.execute.call_args_list if "INSERT" in call[0][0]
        ]
        assert len(insert_calls) == 1
        assert "ON CONFLICT (id) DO NOTHING" in insert_calls[0][0][0]
        seeded_value = insert_calls[0][0][1][0]
        assert before <= seeded_value <= datetime.now(timezone.utc)

    @patch("scoring_service.services.scheduler.settings")
    def test_seed_reproduces_legacy_formula(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        last_attempt = datetime.now(timezone.utc) - timedelta(hours=100)
        conn, cursor = _mock_conn([None, (last_attempt,)])

        assert _is_round_due(conn) is False

        insert_calls = [
            call for call in cursor.execute.call_args_list if "INSERT" in call[0][0]
        ]
        assert len(insert_calls) == 1
        assert insert_calls[0][0][1] == (last_attempt + timedelta(hours=168),)

    @patch("scoring_service.services.scheduler.settings")
    def test_seed_due_after_stale_attempt(self, mock_settings):
        mock_settings.scoring_cadence_hours = 4
        last_attempt = datetime.now(timezone.utc) - timedelta(hours=5)
        conn, _ = _mock_conn([None, (last_attempt,)])

        assert _is_round_due(conn) is True

    @patch("scoring_service.services.scheduler.settings")
    def test_seed_ignores_dry_runs_and_overrides(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn, cursor = _mock_conn([None, None])

        _is_round_due(conn)

        legacy_call = cursor.execute.call_args_list[1]
        sql = legacy_call[0][0]
        params = legacy_call[0][1]
        assert "override_type IS NULL" in sql
        assert "status != %s" in sql
        assert params == ("DRY_RUN_COMPLETE",)


# ---------------------------------------------------------------------------
# _advance_schedule / reanchor_schedule
# ---------------------------------------------------------------------------


class TestAdvanceSchedule:
    @patch("scoring_service.services.scheduler.settings")
    def test_advances_one_cadence(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) - timedelta(hours=1)
        conn, cursor = _mock_conn([(next_due,)])

        result = _advance_schedule(conn)

        update_calls = [
            call for call in cursor.execute.call_args_list if "UPDATE" in call[0][0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0][0][1] == (next_due + timedelta(hours=168),)
        assert result == next_due + timedelta(hours=168)
        assert result > datetime.now(timezone.utc)

    @patch("scoring_service.services.scheduler.settings")
    def test_consumes_missed_slots_in_one_update(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) - timedelta(hours=350)
        conn, cursor = _mock_conn([(next_due,)])

        result = _advance_schedule(conn)

        update_calls = [
            call for call in cursor.execute.call_args_list if "UPDATE" in call[0][0]
        ]
        assert len(update_calls) == 1
        assert result == next_due + timedelta(hours=3 * 168)
        assert result > datetime.now(timezone.utc)

    @patch("scoring_service.services.scheduler.settings")
    def test_future_value_written_unchanged(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        next_due = datetime.now(timezone.utc) + timedelta(hours=10)
        conn, cursor = _mock_conn([(next_due,)])

        result = _advance_schedule(conn)

        update_calls = [
            call for call in cursor.execute.call_args_list if "UPDATE" in call[0][0]
        ]
        assert update_calls[0][0][1] == (next_due,)
        assert result == next_due

    @patch("scoring_service.services.scheduler.settings")
    def test_returns_none_when_row_missing(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn, cursor = _mock_conn([None])

        assert _advance_schedule(conn) is None
        assert not any("UPDATE" in sql for sql in _executed_sql(cursor))

    @patch("scoring_service.services.scheduler.settings")
    def test_raises_on_nonpositive_cadence(self, mock_settings):
        mock_settings.scoring_cadence_hours = 0
        conn, _ = _mock_conn([])

        with pytest.raises(ValueError):
            _advance_schedule(conn)


class TestReanchorSchedule:
    @patch("scoring_service.services.scheduler.settings")
    def test_upserts_now_plus_cadence(self, mock_settings):
        mock_settings.scoring_cadence_hours = 168
        conn, cursor = _mock_conn([])
        before = datetime.now(timezone.utc)

        result = reanchor_schedule(conn)

        sql = cursor.execute.call_args[0][0]
        params = cursor.execute.call_args[0][1]
        assert "ON CONFLICT (id) DO UPDATE" in sql
        assert params == (result,)
        cadence = timedelta(hours=168)
        assert before + cadence <= result <= datetime.now(timezone.utc) + cadence


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
    @patch("scoring_service.services.scheduler._advance_schedule")
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_triggers_round_when_due(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due,
        mock_get_db, mock_advance,
    ):
        _patch_scheduler_settings(mock_settings)
        conn = MagicMock()
        mock_get_db.return_value = conn
        mock_due.return_value = True
        mock_lock.return_value = True
        events = []

        call_count = 0
        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        mock_orchestrator = MagicMock()

        def advance_schedule(advance_conn):
            events.append("advance")
            assert advance_conn is conn

        def run_round():
            events.append("run")
            assert not conn.close.called
            return {"status": "COMPLETE", "round_number": 1}

        def release_lock(release_conn):
            events.append("release")
            assert release_conn is conn
            assert not conn.close.called

        mock_advance.side_effect = advance_schedule
        mock_orchestrator.run_round.side_effect = run_round
        mock_release.side_effect = release_lock

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_orchestrator.run_round.assert_called_once()
        assert events == ["advance", "run", "release"]
        assert conn.autocommit is True
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler._advance_schedule")
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_skips_when_not_due(
        self, mock_settings, mock_sleep, mock_due, mock_get_db, mock_advance,
    ):
        _patch_scheduler_settings(mock_settings)
        conn = MagicMock()
        mock_get_db.return_value = conn
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
        mock_advance.assert_not_called()
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_releases_lock_before_not_due_sleep(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due, mock_get_db,
    ):
        _patch_scheduler_settings(mock_settings)
        conn = MagicMock()
        events = []
        mock_get_db.return_value = conn
        mock_lock.return_value = True
        mock_due.return_value = False

        def release_lock(release_conn):
            assert release_conn is conn
            events.append("release")

        def close_connection():
            events.append("close")

        async def stop_on_interval_sleep(seconds):
            if seconds == mock_settings.scheduler_check_interval_seconds:
                events.append("sleep")
                raise asyncio.CancelledError()

        mock_release.side_effect = release_lock
        conn.close.side_effect = close_connection
        mock_sleep.side_effect = stop_on_interval_sleep

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=MagicMock())

        assert events == ["release", "close", "sleep"]

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
        conn = MagicMock()
        mock_get_db.return_value = conn
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
        mock_release.assert_not_called()
        conn.close.assert_called_once()

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
    @patch("scoring_service.services.scheduler._advance_schedule")
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_releases_lock_after_round(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due,
        mock_get_db, mock_advance,
    ):
        _patch_scheduler_settings(mock_settings)
        conn = MagicMock()
        mock_get_db.return_value = conn
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

        mock_release.assert_called_once_with(conn)
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("scoring_service.services.scheduler._advance_schedule")
    @patch("scoring_service.services.scheduler.get_db")
    @patch("scoring_service.services.scheduler._is_round_due")
    @patch("scoring_service.services.scheduler._try_acquire_lock")
    @patch("scoring_service.services.scheduler._release_lock")
    @patch("scoring_service.services.scheduler.asyncio.sleep")
    @patch("scoring_service.services.scheduler.settings")
    async def test_releases_lock_after_round_failure(
        self, mock_settings, mock_sleep, mock_release, mock_lock, mock_due,
        mock_get_db, mock_advance,
    ):
        _patch_scheduler_settings(mock_settings)
        conn = MagicMock()
        mock_get_db.return_value = conn
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
        mock_orchestrator.run_round.side_effect = RuntimeError("round failed")

        with pytest.raises(asyncio.CancelledError):
            await scheduler_loop(orchestrator=mock_orchestrator)

        mock_advance.assert_called_once_with(conn)
        mock_release.assert_called_once_with(conn)
        conn.close.assert_called_once()
