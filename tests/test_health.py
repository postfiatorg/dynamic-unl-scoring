"""Health endpoint tests."""

from unittest.mock import MagicMock, patch

from fastapi import status


def test_health_returns_ok(client):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("scoring_service.api.health.get_db", return_value=mock_conn):
        response = client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}
    mock_cursor.execute.assert_called_once_with("SELECT 1")
    mock_conn.close.assert_called_once()
