"""Tests for the scoring status API endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import status


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
