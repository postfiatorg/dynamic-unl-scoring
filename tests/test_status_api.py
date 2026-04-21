"""Tests for the scoring status API endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status

from scoring_service.api.scoring import clear_wallet_cache
from scoring_service.config import settings


SAMPLE_ROUND_ROW = (
    1,                                          # id
    1,                                          # round_number
    "COMPLETE",                                 # status
    "abc123",                                   # snapshot_hash
    "def456",                                   # scores_hash
    42,                                         # vl_sequence
    "QmRootCID",                                # ipfs_cid
    "https://github.com/postfiatorg/postfiatorg.github.io/commit/abc",  # github_pages_commit_url
    "TXHASH123",                                # memo_tx_hash
    None,                                       # override_type
    None,                                       # override_reason
    None,                                       # error_message
    datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc),  # started_at
    datetime(2026, 4, 7, 12, 2, 0, tzinfo=timezone.utc),  # completed_at
    datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc),  # created_at
)


def _mock_db_with_rows(rows, total=None):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    if total is not None:
        cursor.fetchall.return_value = rows
        cursor.fetchone.return_value = (total,)
    else:
        cursor.fetchone.return_value = rows[0] if rows else None
    return conn


# ---------------------------------------------------------------------------
# GET /api/scoring/rounds
# ---------------------------------------------------------------------------


class TestListRounds:
    def test_returns_rounds_with_pagination(self, client):
        conn = _mock_db_with_rows([SAMPLE_ROUND_ROW], total=1)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["limit"] == 20
        assert data["offset"] == 0
        assert len(data["rounds"]) == 1
        assert data["rounds"][0]["round_number"] == 1
        assert data["rounds"][0]["status"] == "COMPLETE"

    def test_custom_limit_and_offset(self, client):
        conn = _mock_db_with_rows([], total=0)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds?limit=5&offset=10")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 10

    def test_empty_results(self, client):
        conn = _mock_db_with_rows([], total=0)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["rounds"] == []
        assert data["total"] == 0

    def test_serializes_timestamps(self, client):
        conn = _mock_db_with_rows([SAMPLE_ROUND_ROW], total=1)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds")

        round_data = response.json()["rounds"][0]
        assert round_data["started_at"] is not None
        assert "2026-04-07" in round_data["started_at"]

    def test_handles_null_timestamps(self, client):
        row_with_nulls = (1, 1, "COLLECTING", None, None, None, None, None, None, None, None, None, None, None, datetime(2026, 4, 7, tzinfo=timezone.utc))
        conn = _mock_db_with_rows([row_with_nulls], total=1)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds")

        round_data = response.json()["rounds"][0]
        assert round_data["started_at"] is None
        assert round_data["completed_at"] is None

    def test_content_type_is_json(self, client):
        conn = _mock_db_with_rows([], total=0)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds")

        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /api/scoring/rounds/{round_id}
# ---------------------------------------------------------------------------


class TestGetRound:
    def test_returns_round_detail(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = SAMPLE_ROUND_ROW

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds/1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == 1
        assert data["round_number"] == 1
        assert data["status"] == "COMPLETE"
        assert data["ipfs_cid"] == "QmRootCID"
        assert data["github_pages_commit_url"] == "https://github.com/postfiatorg/postfiatorg.github.io/commit/abc"
        assert data["memo_tx_hash"] == "TXHASH123"
        assert data["vl_sequence"] == 42

    def test_returns_404_when_not_found(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["error"]

    def test_includes_error_message_for_failed_round(self, client):
        failed_row = (1, 1, "FAILED", None, None, None, None, None, None, None, None, "VHS unreachable", None, None, datetime(2026, 4, 7, tzinfo=timezone.utc))
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = failed_row

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/rounds/1")

        data = response.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == "VHS unreachable"


# ---------------------------------------------------------------------------
# GET /api/scoring/unl/current
# ---------------------------------------------------------------------------


class TestGetCurrentUNL:
    def test_returns_unl_from_latest_complete_round(self, client):
        conn = MagicMock()
        cursor1 = MagicMock()
        cursor2 = MagicMock()
        conn.cursor.side_effect = [cursor1, cursor2]
        cursor1.fetchone.return_value = (5,)
        cursor2.fetchone.return_value = ({"unl": ["key_a", "key_b"], "alternates": ["key_c"]},)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/unl/current")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["round_number"] == 5
        assert data["unl"] == ["key_a", "key_b"]
        assert data["alternates"] == ["key_c"]

    def test_returns_404_when_no_completed_rounds(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/unl/current")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "No completed" in response.json()["error"]

    def test_returns_404_when_unl_file_missing(self, client):
        conn = MagicMock()
        cursor1 = MagicMock()
        cursor2 = MagicMock()
        conn.cursor.side_effect = [cursor1, cursor2]
        cursor1.fetchone.return_value = (5,)
        cursor2.fetchone.return_value = None

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/unl/current")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["error"]

    def test_content_type_is_json(self, client):
        conn = MagicMock()
        cursor1 = MagicMock()
        cursor2 = MagicMock()
        conn.cursor.side_effect = [cursor1, cursor2]
        cursor1.fetchone.return_value = (1,)
        cursor2.fetchone.return_value = ({"unl": [], "alternates": []},)

        with patch("scoring_service.api.scoring.get_db", return_value=conn):
            response = client.get("/api/scoring/unl/current")

        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /api/scoring/config
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_returns_200(self, client):
        response = client.get("/api/scoring/config")
        assert response.status_code == status.HTTP_200_OK

    def test_returns_exactly_four_fields(self, client):
        response = client.get("/api/scoring/config")
        assert set(response.json().keys()) == {
            "cadence_hours",
            "unl_score_cutoff",
            "unl_max_size",
            "unl_min_score_gap",
        }

    def test_reflects_live_settings(self, client):
        response = client.get("/api/scoring/config")
        data = response.json()
        assert data["cadence_hours"] == float(settings.scoring_cadence_hours)
        assert data["unl_score_cutoff"] == settings.unl_score_cutoff
        assert data["unl_max_size"] == settings.unl_max_size
        assert data["unl_min_score_gap"] == settings.unl_min_score_gap

    def test_cadence_hours_is_float(self, client):
        response = client.get("/api/scoring/config")
        assert isinstance(response.json()["cadence_hours"], float)

    def test_unl_fields_are_ints(self, client):
        response = client.get("/api/scoring/config")
        data = response.json()
        for field in ("unl_score_cutoff", "unl_max_size", "unl_min_score_gap"):
            value = data[field]
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{field} must be int, got {type(value).__name__}"
            )

    def test_reflects_overridden_settings(self, client, monkeypatch):
        monkeypatch.setattr(settings, "scoring_cadence_hours", 1.5)
        monkeypatch.setattr(settings, "unl_score_cutoff", 55)
        monkeypatch.setattr(settings, "unl_max_size", 7)
        monkeypatch.setattr(settings, "unl_min_score_gap", 3)

        response = client.get("/api/scoring/config")
        data = response.json()
        assert data["cadence_hours"] == 1.5
        assert data["unl_score_cutoff"] == 55
        assert data["unl_max_size"] == 7
        assert data["unl_min_score_gap"] == 3

    def test_requires_no_auth(self, client):
        response = client.get("/api/scoring/config")
        assert response.status_code == status.HTTP_200_OK

    def test_content_type_is_json(self, client):
        response = client.get("/api/scoring/config")
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /api/scoring/health
# ---------------------------------------------------------------------------


FROZEN_NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)


def _mock_health_db(
    scheduler_last_created: datetime | None,
    last_round_row: tuple | None,
):
    conn = MagicMock()
    scheduler_cursor = MagicMock()
    llm_cursor = MagicMock()
    conn.cursor.side_effect = [scheduler_cursor, llm_cursor]
    scheduler_cursor.fetchone.return_value = (
        (scheduler_last_created,) if scheduler_last_created is not None else None
    )
    llm_cursor.fetchone.return_value = last_round_row
    return conn


def _mock_pftl_client_class(balance_drops: int | None = None, raise_exc: Exception | None = None):
    client_instance = MagicMock()
    if raise_exc is not None:
        client_instance.get_balance_drops.side_effect = raise_exc
    else:
        client_instance.get_balance_drops.return_value = balance_drops
    client_class = MagicMock(return_value=client_instance)
    return client_class


@pytest.fixture(autouse=True)
def _reset_wallet_cache():
    clear_wallet_cache()
    yield
    clear_wallet_cache()


class TestGetPipelineHealth:
    # -----------------------------------------------------------------
    # Response shape
    # -----------------------------------------------------------------

    def test_returns_200_with_three_signals(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=15),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        pftl_class = _mock_pftl_client_class(balance_drops=50 * 1_000_000)

        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert set(data.keys()) == {"scheduler", "llm_endpoint", "publisher_wallet"}
        for signal in data.values():
            assert set(signal.keys()) == {"healthy", "detail"}
            assert isinstance(signal["healthy"], bool)
            assert isinstance(signal["detail"], str)

    # -----------------------------------------------------------------
    # Scheduler branch
    # -----------------------------------------------------------------

    def test_scheduler_healthy_when_last_tick_recent(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=30),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["scheduler"]["healthy"] is True
        assert "last tick" in data["scheduler"]["detail"]

    def test_scheduler_unhealthy_when_last_tick_stale(self, client):
        # cadence 1.5h → threshold 3h; 5h elapsed is stale
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(hours=5),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["scheduler"]["healthy"] is False

    def test_scheduler_unhealthy_when_no_rounds_yet(self, client):
        conn = _mock_health_db(
            scheduler_last_created=None,
            last_round_row=None,
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["scheduler"]["healthy"] is False
        assert "no rounds" in data["scheduler"]["detail"]

    # -----------------------------------------------------------------
    # LLM endpoint branch
    # -----------------------------------------------------------------

    def test_llm_healthy_when_last_round_complete(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "snap_hash", "scores_hash"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["llm_endpoint"]["healthy"] is True

    def test_llm_unhealthy_when_last_failed_at_scoring_stage(self, client):
        # snapshot was collected but scores never produced → LLM was the culprit
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("FAILED", "snap_hash", None),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["llm_endpoint"]["healthy"] is False
        assert "scoring stage" in data["llm_endpoint"]["detail"]

    def test_llm_healthy_when_last_failed_after_scoring_stage(self, client):
        # scores were produced, failure happened at a later stage (e.g. IPFS)
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("FAILED", "snap_hash", "scores_hash"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["llm_endpoint"]["healthy"] is True

    def test_llm_healthy_when_no_rounds_yet(self, client):
        conn = _mock_health_db(
            scheduler_last_created=None,
            last_round_row=None,
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(raise_exc=RuntimeError("skip"))),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["llm_endpoint"]["healthy"] is True

    # -----------------------------------------------------------------
    # Publisher wallet branch
    # -----------------------------------------------------------------

    def test_wallet_healthy_with_sufficient_balance(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        # 50 PFT in drops, well above the 10-PFT minimum
        pftl_class = _mock_pftl_client_class(balance_drops=50 * 1_000_000)
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["publisher_wallet"]["healthy"] is True
        assert "50" in data["publisher_wallet"]["detail"]

    def test_wallet_unhealthy_with_low_balance(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        # 1 PFT, below the 10-PFT minimum
        pftl_class = _mock_pftl_client_class(balance_drops=1_000_000)
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["publisher_wallet"]["healthy"] is False
        assert "below minimum" in data["publisher_wallet"]["detail"]

    def test_wallet_unhealthy_on_rpc_failure(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        pftl_class = _mock_pftl_client_class(
            raise_exc=RuntimeError("account_info failed: actNotFound")
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        data = response.json()
        assert data["publisher_wallet"]["healthy"] is False
        assert "RPC unreachable" in data["publisher_wallet"]["detail"]

    # -----------------------------------------------------------------
    # Wallet cache
    # -----------------------------------------------------------------

    def test_wallet_cache_hits_within_ttl(self, client):
        conn_factory = lambda: _mock_health_db(  # noqa: E731
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        pftl_instance = MagicMock()
        pftl_instance.get_balance_drops.return_value = 50 * 1_000_000
        pftl_class = MagicMock(return_value=pftl_instance)

        clock = [1_000_000.0]

        def fake_now_seconds():
            return clock[0]

        with (
            patch(
                "scoring_service.api.scoring.get_db",
                side_effect=lambda: conn_factory(),
            ),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch(
                "scoring_service.api.scoring._monotonic_seconds",
                side_effect=fake_now_seconds,
            ),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            client.get("/api/scoring/health")
            clock[0] += 10  # 10s later — within 30s TTL
            client.get("/api/scoring/health")
            clock[0] += 15  # 25s elapsed total — still within TTL
            client.get("/api/scoring/health")

        # Only one actual RPC call despite three requests
        assert pftl_instance.get_balance_drops.call_count == 1

    def test_wallet_cache_misses_after_ttl(self, client):
        conn_factory = lambda: _mock_health_db(  # noqa: E731
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        pftl_instance = MagicMock()
        pftl_instance.get_balance_drops.return_value = 50 * 1_000_000
        pftl_class = MagicMock(return_value=pftl_instance)

        clock = [1_000_000.0]

        def fake_now_seconds():
            return clock[0]

        with (
            patch(
                "scoring_service.api.scoring.get_db",
                side_effect=lambda: conn_factory(),
            ),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch(
                "scoring_service.api.scoring._monotonic_seconds",
                side_effect=fake_now_seconds,
            ),
            patch("scoring_service.api.scoring.PFTLClient", pftl_class),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            client.get("/api/scoring/health")
            clock[0] += 31  # past 30s TTL
            client.get("/api/scoring/health")

        # Two distinct RPC calls — cache expired between requests
        assert pftl_instance.get_balance_drops.call_count == 2

    # -----------------------------------------------------------------
    # Misc
    # -----------------------------------------------------------------

    def test_content_type_is_json(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(balance_drops=50 * 1_000_000)),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        assert "application/json" in response.headers["content-type"]

    def test_requires_no_auth(self, client):
        conn = _mock_health_db(
            scheduler_last_created=FROZEN_NOW - timedelta(minutes=10),
            last_round_row=("COMPLETE", "abc", "def"),
        )
        with (
            patch("scoring_service.api.scoring.get_db", return_value=conn),
            patch("scoring_service.api.scoring._utcnow", return_value=FROZEN_NOW),
            patch("scoring_service.api.scoring.PFTLClient", _mock_pftl_client_class(balance_drops=50 * 1_000_000)),
            patch("scoring_service.api.scoring.settings", scoring_cadence_hours=1.5),
        ):
            response = client.get("/api/scoring/health")

        assert response.status_code == status.HTTP_200_OK
