"""Tests for the admin override endpoints — custom UNL publish and rollback."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import status


VALID_KEYS = [
    "nHUDXa2bH68Zm5Fmg2WaDSeyEYbiqzMLXussLMyK3t6bTCNiHKY2",
    "nHBgo2xSUVPy4zsWb1NM7CYmyYeobx7Swa3gFgoB55ipuyJwRdKX",
]


# ---------------------------------------------------------------------------
# POST /api/scoring/admin/publish-unl/custom
# ---------------------------------------------------------------------------


class TestPublishCustomUNL:
    def test_rejects_missing_api_key(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                json={"master_keys": VALID_KEYS, "reason": "test"},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Invalid API key" in response.json()["error"]

    def test_rejects_wrong_api_key(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "wrong"},
                json={"master_keys": VALID_KEYS, "reason": "test"},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_rejects_when_admin_key_not_configured(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = ""

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "anything"},
                json={"master_keys": VALID_KEYS, "reason": "test"},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "not configured" in response.json()["error"]

    def test_rejects_empty_master_keys(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={"master_keys": [], "reason": "test"},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_rejects_missing_reason(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={"master_keys": VALID_KEYS},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_rejects_empty_reason(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={"master_keys": VALID_KEYS, "reason": ""},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_rejects_negative_lookahead(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={
                    "master_keys": VALID_KEYS,
                    "reason": "test",
                    "effective_lookahead_hours": -1,
                },
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_returns_409_when_lock_held(self, client):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=False):
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={"master_keys": VALID_KEYS, "reason": "test"},
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already in progress" in response.json()["error"]

    def test_returns_202_and_starts_background_thread(self, client):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
             patch("scoring_service.api._helpers._release_lock"), \
             patch("scoring_service.api.admin.threading.Thread") as mock_thread:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={
                    "master_keys": VALID_KEYS,
                    "reason": "Parity transition — seed VL",
                    "effective_lookahead_hours": 0,
                },
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["override_type"] == "custom"
        assert body["status"] == "started"

        mock_thread.assert_called_once()
        thread_args = mock_thread.call_args.kwargs["args"]
        assert thread_args[0] == VALID_KEYS
        assert thread_args[1] == "Parity transition — seed VL"
        assert thread_args[2] == "custom"
        assert thread_args[3] == 0
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/scoring/admin/publish-unl/from-round/{round_id}
# ---------------------------------------------------------------------------


class TestPublishFromRound:
    def test_rejects_wrong_api_key(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "wrong"},
                json={"reason": "rollback"},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_404_for_unknown_round(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=conn):
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/999",
                headers={"X-API-Key": "the_key"},
                json={"reason": "rollback"},
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "999 not found" in response.json()["error"]

    def test_returns_404_when_unl_file_missing(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=conn), \
             patch("scoring_service.api.admin.get_audit_trail_file", return_value=None):
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={"reason": "rollback"},
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "no unl.json" in response.json()["error"].lower()

    def test_returns_422_when_unl_empty(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=conn), \
             patch(
                 "scoring_service.api.admin.get_audit_trail_file",
                 return_value={"unl": [], "alternates": []},
             ):
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={"reason": "rollback"},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "no UNL master keys" in response.json()["error"]

    def test_returns_409_when_lock_held(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=conn), \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch(
                 "scoring_service.api.admin.get_audit_trail_file",
                 return_value={"unl": VALID_KEYS, "alternates": []},
             ), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=False):
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={"reason": "rollback"},
            )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_returns_202_with_rollback_type_and_source_round(self, client):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=conn), \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch(
                 "scoring_service.api.admin.get_audit_trail_file",
                 return_value={"unl": VALID_KEYS, "alternates": []},
             ), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
             patch("scoring_service.api._helpers._release_lock"), \
             patch("scoring_service.api.admin.threading.Thread") as mock_thread:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={"reason": "Round 6 produced anomalous output"},
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["override_type"] == "rollback"
        assert body["source_round_id"] == 5
        assert body["source_round_number"] == 42
        assert body["status"] == "started"

        thread_args = mock_thread.call_args.kwargs["args"]
        assert thread_args[0] == VALID_KEYS
        assert thread_args[1] == "Round 6 produced anomalous output"
        assert thread_args[2] == "rollback"

    def test_rejects_missing_reason(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
