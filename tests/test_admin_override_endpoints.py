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
        (
            master_keys,
            reason,
            override_type,
            effective_lookahead_hours,
            expiration_days,
            lock_conn,
        ) = thread_args
        assert master_keys == VALID_KEYS
        assert reason == "Parity transition — seed VL"
        assert override_type == "custom"
        assert effective_lookahead_hours == 0
        assert expiration_days is None
        assert lock_conn is conn
        assert lock_conn.autocommit is True
        mock_thread.return_value.start.assert_called_once()

    def test_does_not_release_lock_before_custom_background_thread_runs(self, client):
        conn = MagicMock()

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
             patch("scoring_service.api.admin.release_round_lock") as mock_release, \
             patch("scoring_service.api.admin.threading.Thread") as mock_thread:
            mock_settings.admin_api_key = "the_key"
            mock_thread.return_value = MagicMock()

            response = client.post(
                "/api/scoring/admin/publish-unl/custom",
                headers={"X-API-Key": "the_key"},
                json={"master_keys": VALID_KEYS, "reason": "test"},
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_release.assert_not_called()

    def test_releases_lock_when_custom_thread_start_fails(self, client):
        conn = MagicMock()

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api._helpers.get_db", return_value=conn), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
             patch("scoring_service.api.admin.release_round_lock") as mock_release, \
             patch("scoring_service.api.admin.threading.Thread") as mock_thread:
            mock_settings.admin_api_key = "the_key"
            mock_thread.return_value.start.side_effect = RuntimeError("thread failed")

            with pytest.raises(RuntimeError):
                client.post(
                    "/api/scoring/admin/publish-unl/custom",
                    headers={"X-API-Key": "the_key"},
                    json={"master_keys": VALID_KEYS, "reason": "test"},
                )

        mock_release.assert_called_once_with(conn)


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
        lookup_conn = MagicMock()
        lock_conn = MagicMock()
        cursor = MagicMock()
        lookup_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=lookup_conn), \
             patch("scoring_service.api._helpers.get_db", return_value=lock_conn), \
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
        lookup_conn = MagicMock()
        lock_conn = MagicMock()
        cursor = MagicMock()
        lookup_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=lookup_conn), \
             patch("scoring_service.api._helpers.get_db", return_value=lock_conn), \
             patch(
                 "scoring_service.api.admin.get_audit_trail_file",
                 return_value={"unl": VALID_KEYS, "alternates": []},
             ), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
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
        (
            master_keys,
            reason,
            override_type,
            effective_lookahead_hours,
            expiration_days,
            acquired_lock_conn,
        ) = thread_args
        assert master_keys == VALID_KEYS
        assert reason == "Round 6 produced anomalous output"
        assert override_type == "rollback"
        assert effective_lookahead_hours is None
        assert expiration_days is None
        assert acquired_lock_conn is lock_conn

    def test_releases_lock_when_rollback_thread_start_fails(self, client):
        lookup_conn = MagicMock()
        lock_conn = MagicMock()
        cursor = MagicMock()
        lookup_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch("scoring_service.api._helpers.settings") as mock_settings, \
             patch("scoring_service.api.admin.get_db", return_value=lookup_conn), \
             patch("scoring_service.api._helpers.get_db", return_value=lock_conn), \
             patch(
                 "scoring_service.api.admin.get_audit_trail_file",
                 return_value={"unl": VALID_KEYS, "alternates": []},
             ), \
             patch("scoring_service.api._helpers._try_acquire_lock", return_value=True), \
             patch("scoring_service.api.admin.release_round_lock") as mock_release, \
             patch("scoring_service.api.admin.threading.Thread") as mock_thread:
            mock_settings.admin_api_key = "the_key"
            mock_thread.return_value.start.side_effect = RuntimeError("thread failed")

            with pytest.raises(RuntimeError):
                client.post(
                    "/api/scoring/admin/publish-unl/from-round/5",
                    headers={"X-API-Key": "the_key"},
                    json={"reason": "rollback"},
                )

        mock_release.assert_called_once_with(lock_conn)

    def test_rejects_missing_reason(self, client):
        with patch("scoring_service.api._helpers.settings") as mock_settings:
            mock_settings.admin_api_key = "the_key"

            response = client.post(
                "/api/scoring/admin/publish-unl/from-round/5",
                headers={"X-API-Key": "the_key"},
                json={},
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestBackgroundOverrideExecution:
    @patch("scoring_service.api.admin.release_round_lock")
    @patch("scoring_service.api.admin.ScoringOrchestrator")
    def test_releases_lock_after_override_publish(
        self, mock_orchestrator_class, mock_release_round_lock,
    ):
        from scoring_service.api.admin import _run_override_in_background

        lock_conn = MagicMock()
        events = []
        mock_orchestrator = mock_orchestrator_class.return_value

        def run_override_round(**kwargs):
            events.append("run")
            return {"status": "COMPLETE", "round_number": 7}

        mock_orchestrator.run_override_round.side_effect = run_override_round
        mock_release_round_lock.side_effect = lambda conn: events.append("release")

        _run_override_in_background(
            master_keys=VALID_KEYS,
            reason="test",
            override_type="custom",
            effective_lookahead_hours=None,
            expiration_days=None,
            lock_conn=lock_conn,
        )

        mock_orchestrator.run_override_round.assert_called_once()
        mock_release_round_lock.assert_called_once_with(lock_conn)
        assert events == ["run", "release"]

    @patch("scoring_service.api.admin.release_round_lock")
    @patch("scoring_service.api.admin.ScoringOrchestrator")
    def test_releases_lock_after_override_publish_failure(
        self, mock_orchestrator_class, mock_release_round_lock,
    ):
        from scoring_service.api.admin import _run_override_in_background

        lock_conn = MagicMock()
        mock_orchestrator = mock_orchestrator_class.return_value
        mock_orchestrator.run_override_round.side_effect = RuntimeError("boom")

        _run_override_in_background(
            master_keys=VALID_KEYS,
            reason="test",
            override_type="custom",
            effective_lookahead_hours=None,
            expiration_days=None,
            lock_conn=lock_conn,
        )

        mock_release_round_lock.assert_called_once_with(lock_conn)
