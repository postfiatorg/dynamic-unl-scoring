"""Tests for the VL serving endpoint and storage functions."""

import json
from unittest.mock import MagicMock, patch

from fastapi import status

from scoring_service.services.vl_sequence import get_current_vl, store_vl


SAMPLE_VL = {
    "public_key": "ED3F1E0DA736FCF99BE2880A60DBD470715C0E04DD793FB862236B070571FC09E2",
    "manifest": "JAAAAAFxIe0/Hg2nNvz5m+KICmDb1HBxXA4E3Xk/uGIjawcFcfwJ4g==",
    "blobs_v2": [
        {
            "blob": "eyJzZXF1ZW5jZSI6MSwiZXhwaXJhdGlvbiI6ODY3NzE1MjAwLCJ2YWxpZGF0b3JzIjpbXX0=",
            "signature": "3045022100ABCDEF",
        }
    ],
    "version": 2,
}


# ---------------------------------------------------------------------------
# store_vl
# ---------------------------------------------------------------------------


class TestStoreVL:
    def test_writes_vl_data(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        store_vl(conn, SAMPLE_VL)

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "vl_data" in sql
        assert json.loads(params[0]) == SAMPLE_VL

    def test_stores_valid_json(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        store_vl(conn, SAMPLE_VL)

        params = cursor.execute.call_args[0][1]
        roundtripped = json.loads(params[0])
        assert roundtripped["version"] == 2
        assert roundtripped["public_key"] == SAMPLE_VL["public_key"]


# ---------------------------------------------------------------------------
# get_current_vl
# ---------------------------------------------------------------------------


class TestGetCurrentVL:
    def test_returns_vl_when_present(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (SAMPLE_VL,)

        result = get_current_vl(conn)
        assert result == SAMPLE_VL

    def test_returns_none_when_no_row(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = get_current_vl(conn)
        assert result is None

    def test_returns_none_when_vl_data_is_null(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (None,)

        result = get_current_vl(conn)
        assert result is None


# ---------------------------------------------------------------------------
# GET /vl.json endpoint
# ---------------------------------------------------------------------------


class TestVLEndpoint:
    def test_returns_vl_when_published(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (SAMPLE_VL,)

        with patch("scoring_service.api.vl.get_db", return_value=mock_conn):
            response = client.get("/vl.json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == SAMPLE_VL
        mock_conn.close.assert_called_once()

    def test_returns_404_when_no_vl(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (None,)

        with patch("scoring_service.api.vl.get_db", return_value=mock_conn):
            response = client.get("/vl.json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.json()
        mock_conn.close.assert_called_once()

    def test_content_type_is_json(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (SAMPLE_VL,)

        with patch("scoring_service.api.vl.get_db", return_value=mock_conn):
            response = client.get("/vl.json")

        assert "application/json" in response.headers["content-type"]
