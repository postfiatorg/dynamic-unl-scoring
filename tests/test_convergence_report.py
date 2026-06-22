"""Tests for M2.6 convergence report assembly, sealing, and on-chain anchoring."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scoring_service.services import convergence_verification as cv
from scoring_service.services.commit_reveal import CONVERGENCE_REPORT_TYPE
from scoring_service.services.onchain_publisher import OnChainPublisherService

R = 273
META = {
    "network": "devnet",
    "input_package_hash": "a" * 64,
    "input_package_cid": "Qm" + "A" * 44,
    "reveal_opens_at": datetime(2026, 5, 25, 0, 30, tzinfo=timezone.utc),
    "reveal_closes_at": datetime(2026, 5, 25, 1, 0, tzinfo=timezone.utc),  # 30-min window
}
OUTCOME_ROWS = [
    {"validator_master_key": "nHU1", "outcome": "valid", "accepted_commit_tx": "C1",
     "accepted_reveal_tx": "R1", "conflicting_commit": False, "conflicting_reveal": False,
     "comparison_levels_matched": "RAW,PARSED,SELECTED_UNL", "divergence_stage": None,
     "divergence_category": None},
    {"validator_master_key": "nHU2", "outcome": "divergent", "accepted_commit_tx": "C2",
     "accepted_reveal_tx": "R2", "conflicting_commit": False, "conflicting_reveal": False,
     "comparison_levels_matched": "PARSED,SELECTED_UNL", "divergence_stage": "RAW",
     "divergence_category": "OUTPUT_DIVERGENCE"},
    {"validator_master_key": "nHU3", "outcome": "missing_reveal", "accepted_commit_tx": "C3",
     "accepted_reveal_tx": None, "conflicting_commit": False, "conflicting_reveal": False,
     "comparison_levels_matched": None, "divergence_stage": None, "divergence_category": None},
]


class TestAssembleReport:
    def test_assembles_from_stored_outcomes(self):
        conn = MagicMock()
        with patch.object(cv, "_load_announcement_meta", return_value=META), \
                patch.object(cv, "_load_outcome_rows", return_value=OUTCOME_ROWS):
            report = cv.assemble_report(conn, R)

        assert report["type"] == CONVERGENCE_REPORT_TYPE
        assert report["round_number"] == R
        assert report["network"] == "devnet"
        assert report["input_package_hash"] == "a" * 64
        assert len(report["participants"]) == 3
        summary = report["summary"]
        assert summary["committers"] == 3
        assert summary["outcomes"] == {"valid": 1, "divergent": 1, "missing_reveal": 1}
        assert summary["levels_matched"]["RAW"] == 1
        assert summary["levels_matched"]["SELECTED_UNL"] == 2
        assert summary["divergence_categories"] == {"OUTPUT_DIVERGENCE": 1}

    def test_none_without_announcement(self):
        conn = MagicMock()
        with patch.object(cv, "_load_announcement_meta", return_value=None):
            assert cv.assemble_report(conn, R) is None


class TestSealDeadline:
    def test_grace_is_fraction_of_reveal_window(self):
        # 30-min window, default fraction 0.5 -> 15-min grace (above the floor).
        assert cv.seal_deadline(META) == META["reveal_closes_at"] + timedelta(minutes=15)

    def test_grace_floor_applies_to_short_window(self):
        meta = {
            **META,
            "reveal_opens_at": datetime(2026, 5, 25, 0, 30, 0, tzinfo=timezone.utc),
            "reveal_closes_at": datetime(2026, 5, 25, 0, 30, 10, tzinfo=timezone.utc),
        }
        # 0.5 * 10s = 5s, below the 120s floor -> grace is the floor.
        assert cv.seal_deadline(meta) == meta["reveal_closes_at"] + timedelta(seconds=120)


class TestSealRound:
    def _publishers(self, cid="QmCID", anchor="ANCHORTX"):
        ipfs = MagicMock()
        ipfs.publish_convergence_report.return_value = cid
        onchain = MagicMock()
        onchain.publish_convergence_report.return_value = anchor
        return ipfs, onchain

    def test_seals_pins_inserts_and_anchors(self):
        conn = MagicMock()
        ipfs, onchain = self._publishers()
        with patch.object(cv, "_load_sealed_report", return_value=None), \
                patch.object(cv, "assemble_report", return_value={"round_number": R}), \
                patch.object(cv, "_insert_convergence_report", return_value=True), \
                patch.object(cv, "_set_anchor_tx") as set_anchor:
            res = cv.seal_round(conn, R, ipfs_publisher=ipfs, onchain_publisher=onchain)

        assert res["sealed"] is True
        assert res["convergence_bundle_cid"] == "QmCID"
        assert res["anchor_tx_hash"] == "ANCHORTX"
        ipfs.publish_convergence_report.assert_called_once()
        onchain.publish_convergence_report.assert_called_once_with(
            round_number=R, convergence_bundle_cid="QmCID"
        )
        set_anchor.assert_called_once_with(conn, R, "ANCHORTX")

    def test_already_sealed_and_anchored_is_noop(self):
        conn = MagicMock()
        ipfs, onchain = self._publishers()
        sealed = {"convergence_bundle_cid": "QmX", "anchor_tx_hash": "PRIORTX"}
        with patch.object(cv, "_load_sealed_report", return_value=sealed):
            res = cv.seal_round(conn, R, ipfs_publisher=ipfs, onchain_publisher=onchain)

        assert res["sealed"] is False
        assert res["reason"] == "already_sealed"
        ipfs.publish_convergence_report.assert_not_called()
        onchain.publish_convergence_report.assert_not_called()

    def test_sealed_but_unanchored_retries_anchor_without_repinning(self):
        conn = MagicMock()
        ipfs = MagicMock()
        onchain = MagicMock()
        onchain.publish_convergence_report.return_value = "NEWTX"
        sealed = {"convergence_bundle_cid": "QmX", "anchor_tx_hash": None}
        with patch.object(cv, "_load_sealed_report", return_value=sealed), \
                patch.object(cv, "_set_anchor_tx") as set_anchor:
            res = cv.seal_round(conn, R, ipfs_publisher=ipfs, onchain_publisher=onchain)

        assert res["sealed"] is True
        assert res["reason"] == "anchor_retry"
        assert res["anchor_tx_hash"] == "NEWTX"
        ipfs.publish_convergence_report.assert_not_called()  # no re-pin
        onchain.publish_convergence_report.assert_called_once_with(
            round_number=R, convergence_bundle_cid="QmX"
        )
        set_anchor.assert_called_once_with(conn, R, "NEWTX")

    def test_insert_race_to_anchored_winner_does_not_anchor(self):
        conn = MagicMock()
        ipfs, onchain = self._publishers()
        winner = {"convergence_bundle_cid": "QmX", "anchor_tx_hash": "WINTX"}
        with patch.object(cv, "_load_sealed_report", side_effect=[None, winner]), \
                patch.object(cv, "assemble_report", return_value={"round_number": R}), \
                patch.object(cv, "_insert_convergence_report", return_value=False):
            res = cv.seal_round(conn, R, ipfs_publisher=ipfs, onchain_publisher=onchain)

        assert res["sealed"] is False
        assert res["reason"] == "already_sealed"
        onchain.publish_convergence_report.assert_not_called()

    def test_pin_failure_aborts_before_persisting(self):
        conn = MagicMock()
        ipfs, onchain = self._publishers(cid=None)
        with patch.object(cv, "_load_sealed_report", return_value=None), \
                patch.object(cv, "assemble_report", return_value={"round_number": R}), \
                patch.object(cv, "_insert_convergence_report") as insert:
            res = cv.seal_round(conn, R, ipfs_publisher=ipfs, onchain_publisher=onchain)

        assert res["sealed"] is False
        assert res["reason"] == "pin_failed"
        insert.assert_not_called()
        onchain.publish_convergence_report.assert_not_called()


class TestSealDueRounds:
    def _conn_with_rounds(self, rows):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = rows
        return conn

    def test_not_sealable_before_grace_deadline(self):
        conn = self._conn_with_rounds([(R, META["reveal_opens_at"], META["reveal_closes_at"])])
        within_grace = META["reveal_closes_at"] + timedelta(minutes=10)
        assert cv._sealable_rounds(conn, within_grace) == []

    def test_sealable_after_grace_deadline(self):
        conn = self._conn_with_rounds([(R, META["reveal_opens_at"], META["reveal_closes_at"])])
        past_grace = META["reveal_closes_at"] + timedelta(minutes=20)
        assert cv._sealable_rounds(conn, past_grace) == [R]

    def test_seal_due_rounds_covers_due_and_unanchored(self):
        conn = MagicMock()
        now = datetime(2026, 5, 25, 2, 0, tzinfo=timezone.utc)
        with patch.object(cv, "_sealable_rounds", return_value=[273, 274]), \
                patch.object(cv, "_unanchored_rounds", return_value=[270]), \
                patch.object(cv, "seal_round", return_value={"sealed": True}) as seal:
            cv.seal_due_rounds(conn, now, ipfs_publisher=MagicMock(), onchain_publisher=MagicMock())

        sealed_rounds = [c.args[1] for c in seal.call_args_list]
        assert sealed_rounds == [273, 274, 270]


class TestAnchorPayload:
    def test_publish_convergence_report_builds_memo(self):
        pftl = MagicMock()
        pftl.submit_memo.return_value = (True, "TXHASH", None)
        svc = OnChainPublisherService(pftl_client=pftl)

        tx = svc.publish_convergence_report(round_number=R, convergence_bundle_cid="QmCID")

        assert tx == "TXHASH"
        (memo_data,) = pftl.submit_memo.call_args.args
        assert pftl.submit_memo.call_args.kwargs["memo_type"] == CONVERGENCE_REPORT_TYPE
        payload = json.loads(memo_data)
        assert payload["type"] == CONVERGENCE_REPORT_TYPE
        assert payload["round_number"] == R
        assert payload["convergence_bundle_cid"] == "QmCID"

    def test_returns_none_on_submit_failure(self):
        pftl = MagicMock()
        pftl.submit_memo.return_value = (False, None, "tecNO_DST")
        svc = OnChainPublisherService(pftl_client=pftl)
        assert svc.publish_convergence_report(round_number=R, convergence_bundle_cid="QmCID") is None
