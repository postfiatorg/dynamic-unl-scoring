"""Tests for VL sequence number management."""

from unittest.mock import MagicMock, call

import pytest

from scoring_service.services.vl_sequence import (
    confirm_sequence,
    get_confirmed_sequence,
    release_sequence,
    reserve_next_sequence,
)


def _mock_conn(confirmed=0, reserved=None):
    """Build a mock connection that simulates the vl_sequence table."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    state = {"confirmed": confirmed, "reserved": reserved}

    def execute(sql, params=None):
        sql_lower = sql.strip().lower()
        if "reserved_sequence" in sql_lower and sql_lower.startswith("select"):
            cursor.fetchone.return_value = (state["confirmed"], state["reserved"])
        elif sql_lower.startswith("select confirmed_sequence"):
            cursor.fetchone.return_value = (state["confirmed"],)
        elif sql_lower.startswith("update vl_sequence set reserved_sequence"):
            if params and params[0] is not None:
                state["reserved"] = params[0]
            else:
                state["reserved"] = None
            cursor.rowcount = 1
        elif sql_lower.startswith("update vl_sequence set confirmed_sequence"):
            state["confirmed"] = params[0]
            state["reserved"] = None

    cursor.execute = MagicMock(side_effect=execute)
    return conn, state


# ---------------------------------------------------------------------------
# First-round bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_first_reserve_returns_1(self):
        conn, _ = _mock_conn(confirmed=0)
        seq = reserve_next_sequence(conn)
        assert seq == 1

    def test_confirmed_starts_at_0(self):
        conn, _ = _mock_conn(confirmed=0)
        assert get_confirmed_sequence(conn) == 0


# ---------------------------------------------------------------------------
# Normal incrementing
# ---------------------------------------------------------------------------


class TestIncrement:
    def test_reserve_increments_from_confirmed(self):
        conn, _ = _mock_conn(confirmed=5)
        seq = reserve_next_sequence(conn)
        assert seq == 6

    def test_successive_confirms_increment(self):
        conn, state = _mock_conn(confirmed=0)

        seq1 = reserve_next_sequence(conn)
        assert seq1 == 1
        state["reserved"] = seq1
        state["confirmed"] = 0
        confirm_sequence(conn, seq1)

        state["confirmed"] = 1
        state["reserved"] = None
        seq2 = reserve_next_sequence(conn)
        assert seq2 == 2


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------


class TestConfirm:
    def test_confirm_matching_reservation(self):
        conn, state = _mock_conn(confirmed=3, reserved=4)
        confirm_sequence(conn, 4)
        assert state["confirmed"] == 4
        assert state["reserved"] is None

    def test_confirm_rejects_mismatched_sequence(self):
        conn, _ = _mock_conn(confirmed=3, reserved=4)
        with pytest.raises(ValueError, match="current reservation is 4"):
            confirm_sequence(conn, 5)

    def test_confirm_rejects_when_no_reservation(self):
        conn, _ = _mock_conn(confirmed=3, reserved=None)
        with pytest.raises(ValueError, match="current reservation is None"):
            confirm_sequence(conn, 4)

    def test_confirm_rejects_stale_sequence(self):
        conn, _ = _mock_conn(confirmed=5, reserved=3)
        with pytest.raises(ValueError, match="not greater than confirmed value 5"):
            confirm_sequence(conn, 3)


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_clears_reservation(self):
        conn, state = _mock_conn(confirmed=3, reserved=4)
        release_sequence(conn)
        assert state["reserved"] is None

    def test_release_does_not_advance_confirmed(self):
        conn, state = _mock_conn(confirmed=3, reserved=4)
        release_sequence(conn)
        assert state["confirmed"] == 3

    def test_release_is_idempotent(self):
        conn, _ = _mock_conn(confirmed=3, reserved=None)
        release_sequence(conn)  # should not raise


# ---------------------------------------------------------------------------
# Reserve after release (reuse)
# ---------------------------------------------------------------------------


class TestReserveAfterRelease:
    def test_reuses_sequence_after_release(self):
        conn, state = _mock_conn(confirmed=5, reserved=6)
        release_sequence(conn)
        state["reserved"] = None
        seq = reserve_next_sequence(conn)
        assert seq == 6  # same number reused

    def test_overwrites_stale_reservation(self):
        conn, state = _mock_conn(confirmed=5, reserved=6)
        seq = reserve_next_sequence(conn)
        assert seq == 6  # overwrites the existing reservation


# ---------------------------------------------------------------------------
# Safety check (get_confirmed_sequence)
# ---------------------------------------------------------------------------


class TestGetConfirmedSequence:
    def test_returns_confirmed_value(self):
        conn, _ = _mock_conn(confirmed=42)
        assert get_confirmed_sequence(conn) == 42

    def test_returns_0_when_row_missing(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None
        assert get_confirmed_sequence(conn) == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_reserve_raises_when_row_missing(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None
        with pytest.raises(RuntimeError, match="migration 004 not applied"):
            reserve_next_sequence(conn)
