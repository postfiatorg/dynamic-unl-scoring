"""Tests for the manual scoring trigger endpoint."""

from unittest.mock import MagicMock, patch

from fastapi import status


class TestAuth:
    @patch("scoring_service.api.scoring.settings")
    def test_returns_403_when_admin_key_not_configured(self, mock_settings, client):
        mock_settings.admin_api_key = ""

        response = client.post("/api/scoring/trigger")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "not configured" in response.json()["error"]

    @patch("scoring_service.api.scoring.settings")
    def test_returns_403_when_api_key_missing(self, mock_settings, client):
        mock_settings.admin_api_key = "secret-key"

        response = client.post("/api/scoring/trigger")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Invalid" in response.json()["error"]

    @patch("scoring_service.api.scoring.settings")
    def test_returns_403_when_api_key_wrong(self, mock_settings, client):
        mock_settings.admin_api_key = "secret-key"

        response = client.post(
            "/api/scoring/trigger",
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("scoring_service.api.scoring.threading.Thread")
    @patch("scoring_service.api.scoring._release_lock")
    @patch("scoring_service.api.scoring._try_acquire_lock", return_value=True)
    @patch("scoring_service.api.scoring.get_db")
    @patch("scoring_service.api.scoring.settings")
    def test_accepts_valid_api_key(
        self, mock_settings, mock_get_db, mock_lock, mock_release, mock_thread, client,
    ):
        mock_settings.admin_api_key = "secret-key"
        mock_get_db.return_value = MagicMock()
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        response = client.post(
            "/api/scoring/trigger",
            headers={"X-API-Key": "secret-key"},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED


class TestLockContention:
    @patch("scoring_service.api.scoring._try_acquire_lock", return_value=False)
    @patch("scoring_service.api.scoring.get_db")
    @patch("scoring_service.api.scoring.settings")
    def test_returns_409_when_round_in_progress(
        self, mock_settings, mock_get_db, mock_lock, client,
    ):
        mock_settings.admin_api_key = "secret-key"
        mock_get_db.return_value = MagicMock()

        response = client.post(
            "/api/scoring/trigger",
            headers={"X-API-Key": "secret-key"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already in progress" in response.json()["error"]


class TestBackgroundExecution:
    @patch("scoring_service.api.scoring.threading.Thread")
    @patch("scoring_service.api.scoring._release_lock")
    @patch("scoring_service.api.scoring._try_acquire_lock", return_value=True)
    @patch("scoring_service.api.scoring.get_db")
    @patch("scoring_service.api.scoring.settings")
    def test_returns_202_and_starts_thread(
        self, mock_settings, mock_get_db, mock_lock, mock_release, mock_thread, client,
    ):
        mock_settings.admin_api_key = "secret-key"
        mock_get_db.return_value = MagicMock()
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        response = client.post(
            "/api/scoring/trigger",
            headers={"X-API-Key": "secret-key"},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["status"] == "started"
        mock_thread_instance.start.assert_called_once()

    @patch("scoring_service.api.scoring.threading.Thread")
    @patch("scoring_service.api.scoring._release_lock")
    @patch("scoring_service.api.scoring._try_acquire_lock", return_value=True)
    @patch("scoring_service.api.scoring.get_db")
    @patch("scoring_service.api.scoring.settings")
    def test_passes_dry_run_to_thread(
        self, mock_settings, mock_get_db, mock_lock, mock_release, mock_thread, client,
    ):
        mock_settings.admin_api_key = "secret-key"
        mock_get_db.return_value = MagicMock()
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        response = client.post(
            "/api/scoring/trigger?dry_run=true",
            headers={"X-API-Key": "secret-key"},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["dry_run"] is True
        mock_thread.assert_called_once()
        thread_args = mock_thread.call_args
        assert thread_args[1]["args"] == (True,)

    @patch("scoring_service.api.scoring.threading.Thread")
    @patch("scoring_service.api.scoring._release_lock")
    @patch("scoring_service.api.scoring._try_acquire_lock", return_value=True)
    @patch("scoring_service.api.scoring.get_db")
    @patch("scoring_service.api.scoring.settings")
    def test_thread_is_daemon(
        self, mock_settings, mock_get_db, mock_lock, mock_release, mock_thread, client,
    ):
        mock_settings.admin_api_key = "secret-key"
        mock_get_db.return_value = MagicMock()
        mock_thread.return_value = MagicMock()

        client.post(
            "/api/scoring/trigger",
            headers={"X-API-Key": "secret-key"},
        )

        thread_kwargs = mock_thread.call_args[1]
        assert thread_kwargs["daemon"] is True


class TestStaleRoundCleanup:
    @patch("scoring_service.services.orchestrator._cleanup_stale_rounds")
    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_cleanup_called_before_round_creation(
        self, mock_settings, mock_next_rn, mock_create, mock_get_db, mock_cleanup,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        mock_collector = MagicMock()
        mock_collector.collect.side_effect = Exception("stop early")

        from scoring_service.services.orchestrator import ScoringOrchestrator

        orchestrator = ScoringOrchestrator(
            collector=mock_collector,
            prompt_builder=MagicMock(),
            modal_client=MagicMock(),
            rpc_client=MagicMock(),
            ipfs_publisher=MagicMock(),
            onchain_publisher=MagicMock(),
            github_pages_client=MagicMock(),
        )
        orchestrator.run_round()

        mock_cleanup.assert_called_once()

    def test_cleanup_marks_stale_rounds_failed(self):
        from scoring_service.services.orchestrator import _cleanup_stale_rounds, RoundState

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.rowcount = 2

        cleaned = _cleanup_stale_rounds(conn)

        assert cleaned == 2
        conn.commit.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "status NOT IN" in sql

    def test_cleanup_returns_zero_when_no_stale_rounds(self):
        from scoring_service.services.orchestrator import _cleanup_stale_rounds

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.rowcount = 0

        cleaned = _cleanup_stale_rounds(conn)
        assert cleaned == 0
