"""Tests for the M2.6.5 operator-visibility convergence API.

Covers the unified read view (sealed report, live tally, not-tracked) in the
service layer and the two endpoints that expose it, including cache behavior,
no-data handling, and the routing precedence over the audit-trail catch-all.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import status

from scoring_service.api.convergence import CONVERGENCE_LIVE_CACHE_SECONDS
from scoring_service.services import convergence_verification as cv

SEALED_RECORD = {
    "convergence_bundle_cid": "Qm" + "C" * 44,
    "anchor_tx_hash": "A" * 64,
    "report": {
        "type": "pf_dynamic_unl_convergence_report_v1",
        "round_number": 273,
        "participants": [{"validator_master_key": "nHU1", "outcome": "valid"}],
        "summary": {"committers": 1, "outcomes": {"valid": 1}},
    },
    "sealed_at": datetime(2026, 5, 25, 1, 30, tzinfo=timezone.utc),
}

LIVE_REPORT = {
    "type": "pf_dynamic_unl_convergence_report_v1",
    "round_number": 273,
    "network": "devnet",
    "input_package_hash": "a" * 64,
    "input_package_cid": "Qm" + "A" * 44,
    "participants": [{"validator_master_key": "nHU1", "outcome": "valid"}],
    "summary": {"committers": 1, "outcomes": {"valid": 1}},
}


class TestRoundConvergenceView:
    def test_sealed_round_served_from_stored_report(self):
        conn = MagicMock()
        with patch.object(cv, "load_sealed_report", return_value=SEALED_RECORD):
            view = cv.round_convergence_view(conn, 273)

        assert view["phase"] == cv.PHASE_SEALED
        assert view["finalized"] is True
        assert view["convergence_bundle_cid"] == SEALED_RECORD["convergence_bundle_cid"]
        assert view["anchor_tx_hash"] == SEALED_RECORD["anchor_tx_hash"]
        assert view["sealed_at"] == "2026-05-25T01:30:00+00:00"
        assert view["report"] == SEALED_RECORD["report"]

    def test_sealed_round_tolerates_missing_seal_time(self):
        conn = MagicMock()
        record = {**SEALED_RECORD, "sealed_at": None}
        with patch.object(cv, "load_sealed_report", return_value=record):
            view = cv.round_convergence_view(conn, 273)

        assert view["sealed_at"] is None

    def test_live_round_returns_assembled_tally(self):
        conn = MagicMock()
        with (
            patch.object(cv, "load_sealed_report", return_value=None),
            patch.object(cv, "assemble_report", return_value=dict(LIVE_REPORT)),
        ):
            view = cv.round_convergence_view(conn, 273)

        assert view["phase"] == cv.PHASE_LIVE
        assert view["finalized"] is False
        assert view["participants"] == LIVE_REPORT["participants"]
        assert view["summary"]["committers"] == 1

    def test_round_without_announcement_is_not_tracked(self):
        conn = MagicMock()
        with (
            patch.object(cv, "load_sealed_report", return_value=None),
            patch.object(cv, "assemble_report", return_value=None),
        ):
            view = cv.round_convergence_view(conn, 999)

        assert view["phase"] == cv.PHASE_NOT_TRACKED
        assert view["finalized"] is False
        assert view["round_number"] == 999


class TestLatestAnnouncedRound:
    def test_returns_max_round_number(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (273,)

        assert cv.latest_announced_round(conn) == 273

    def test_returns_none_when_no_announcements(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (None,)

        assert cv.latest_announced_round(conn) is None


class TestRoundConvergenceEndpoint:
    def test_sealed_round_is_immutable_cached(self, client):
        view = {"round_number": 273, "phase": "sealed", "finalized": True}
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ),
        ):
            response = client.get("/api/scoring/rounds/273/convergence")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == view
        assert "immutable" in response.headers["cache-control"]

    def test_live_round_has_short_cache(self, client):
        view = {"round_number": 273, "phase": "live", "finalized": False}
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ),
        ):
            response = client.get("/api/scoring/rounds/273/convergence")

        assert response.status_code == status.HTTP_200_OK
        assert "immutable" not in response.headers["cache-control"]
        assert f"max-age={CONVERGENCE_LIVE_CACHE_SECONDS}" in response.headers["cache-control"]

    def test_not_tracked_existing_round_returns_200(self, client):
        view = {"round_number": 50, "phase": "not_tracked", "finalized": False}
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ),
            patch(
                "scoring_service.api.convergence.public_round_exists",
                return_value=True,
            ),
        ):
            response = client.get("/api/scoring/rounds/50/convergence")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["phase"] == "not_tracked"

    def test_unknown_round_returns_404(self, client):
        view = {"round_number": 99999, "phase": "not_tracked", "finalized": False}
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ),
            patch(
                "scoring_service.api.convergence.public_round_exists",
                return_value=False,
            ),
        ):
            response = client.get("/api/scoring/rounds/99999/convergence")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.json()

    def test_route_not_shadowed_by_audit_trail(self, client):
        """`/rounds/{n}/convergence` must hit the convergence handler, not the
        audit-trail `/rounds/{n}/{file_path:path}` catch-all."""
        view = {"round_number": 5, "phase": "live", "finalized": False}
        with (
            patch(
                "scoring_service.api.audit_trail.get_db", return_value=MagicMock()
            ) as audit_db,
            patch(
                "scoring_service.api.convergence.get_db", return_value=MagicMock()
            ) as convergence_db,
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ),
        ):
            response = client.get("/api/scoring/rounds/5/convergence")

        audit_db.assert_not_called()
        convergence_db.assert_called_once()
        assert response.status_code == status.HTTP_200_OK


class TestCurrentConvergenceEndpoint:
    def test_resolves_latest_announced_round(self, client):
        view = {"round_number": 273, "phase": "live", "finalized": False}
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.latest_announced_round",
                return_value=273,
            ),
            patch(
                "scoring_service.api.convergence.round_convergence_view",
                return_value=view,
            ) as view_fn,
        ):
            response = client.get("/api/scoring/convergence/current")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["round_number"] == 273
        assert view_fn.call_args.args[1] == 273

    def test_no_announced_round_returns_not_tracked(self, client):
        with (
            patch("scoring_service.api.convergence.get_db", return_value=MagicMock()),
            patch(
                "scoring_service.api.convergence.latest_announced_round",
                return_value=None,
            ),
        ):
            response = client.get("/api/scoring/convergence/current")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["phase"] == "not_tracked"
        assert body["round_number"] is None
        assert "immutable" not in response.headers["cache-control"]
