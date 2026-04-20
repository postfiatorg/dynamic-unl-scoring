"""Tests for the HTTPS audit trail fallback endpoint."""

from unittest.mock import MagicMock, patch

from fastapi import status


class TestServeAuditTrailFile:
    def test_returns_file_when_present(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ({"round_number": 1, "validators": []},)

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/api/scoring/rounds/1/snapshot.json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"round_number": 1, "validators": []}
        mock_conn.close.assert_called_once()

    def test_returns_404_when_file_missing(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/api/scoring/rounds/1/nonexistent.json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.json()
        mock_conn.close.assert_called_once()

    def test_returns_404_for_missing_round(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/api/scoring/rounds/999/metadata.json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_handles_nested_file_paths(self, client):
        raw_data = {"validators": [{"master_key": "nHU..."}]}
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (raw_data,)

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/api/scoring/rounds/1/raw/vhs_validators.json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == raw_data

        call_args = mock_cursor.execute.call_args[0]
        assert call_args[1] == (1, "raw/vhs_validators.json")

    def test_content_type_is_json(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ({"data": True},)

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/api/scoring/rounds/1/metadata.json")

        assert "application/json" in response.headers["content-type"]

    def test_single_segment_round_path_does_not_hit_audit_handler(self, client):
        """A single-segment URL like `/api/scoring/rounds/14` must route to the
        round-detail handler in `scoring.py`, not the audit-trail handler.

        This guards against a routing collision after the audit-trail router
        was moved under the shared `/api/scoring` prefix in M1.12.3.
        FastAPI distinguishes the two routes by segment count, but this test
        locks that behavior so a future refactor cannot silently reintroduce
        ambiguity.
        """
        audit_conn = MagicMock()
        scoring_conn = MagicMock()
        scoring_cursor = MagicMock()
        scoring_conn.cursor.return_value = scoring_cursor
        scoring_cursor.fetchone.return_value = None

        with (
            patch(
                "scoring_service.api.audit_trail.get_db",
                return_value=audit_conn,
            ) as audit_db,
            patch(
                "scoring_service.api.scoring.get_db",
                return_value=scoring_conn,
            ) as scoring_db,
        ):
            response = client.get("/api/scoring/rounds/14")

        audit_db.assert_not_called()
        scoring_db.assert_called_once()
        assert response.status_code == status.HTTP_404_NOT_FOUND
