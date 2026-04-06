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
            response = client.get("/rounds/1/snapshot.json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"round_number": 1, "validators": []}
        mock_conn.close.assert_called_once()

    def test_returns_404_when_file_missing(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/rounds/1/nonexistent.json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.json()
        mock_conn.close.assert_called_once()

    def test_returns_404_for_missing_round(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/rounds/999/metadata.json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_handles_nested_file_paths(self, client):
        raw_data = {"validators": [{"master_key": "nHU..."}]}
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (raw_data,)

        with patch("scoring_service.api.audit_trail.get_db", return_value=mock_conn):
            response = client.get("/rounds/1/raw/vhs_validators.json")

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
            response = client.get("/rounds/1/metadata.json")

        assert "application/json" in response.headers["content-type"]
