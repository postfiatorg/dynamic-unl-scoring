"""Tests for the scoring orchestrator state machine."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from scoring_service.services.orchestrator import (
    RoundState,
    ScoringOrchestrator,
    _create_round,
    _fail_round,
    _get_previous_unl,
    _next_round_number,
    _update_round,
)
from scoring_service.services.response_parser import ScoringResult, ValidatorScore
from scoring_service.services.unl_selector import UNLSelectionResult


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _mock_conn():
    """Create a mock DB connection with cursor support."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _make_scoring_result(complete=True, validator_count=2):
    scores = [
        ValidatorScore(
            master_key=f"nHU_key_{i}",
            score=80 + i,
            consensus=85,
            reliability=80,
            software=75,
            diversity=70,
            identity=65,
            reasoning=f"Validator {i} reasoning",
        )
        for i in range(validator_count)
    ]
    return ScoringResult(
        validator_scores=scores,
        network_summary="Test network summary",
        raw_response='{"test": true}',
        complete=complete,
        errors=[] if complete else ["Some error"],
    )


def _make_unl_result():
    return UNLSelectionResult(
        unl=["nHU_key_0", "nHU_key_1"],
        alternates=[],
    )


def _mock_snapshot():
    snapshot = MagicMock()
    snapshot.content_hash.return_value = "abc123hash"
    return snapshot


SAMPLE_VL = {"public_key": "ED...", "version": 2, "blobs_v2": []}


# ---------------------------------------------------------------------------
# Round number generation
# ---------------------------------------------------------------------------


class TestNextRoundNumber:
    def test_returns_1_when_no_rounds_exist(self):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = (0,)

        assert _next_round_number(conn) == 1

    def test_increments_from_max(self):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = (5,)

        assert _next_round_number(conn) == 6


# ---------------------------------------------------------------------------
# Round lifecycle helpers
# ---------------------------------------------------------------------------


class TestCreateRound:
    def test_returns_round_id(self):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = (42,)

        round_id = _create_round(conn, 1)
        assert round_id == 42
        conn.commit.assert_called_once()

    def test_inserts_with_collecting_status(self):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = (1,)

        _create_round(conn, 1)

        insert_sql = cursor.execute.call_args[0][0]
        params = cursor.execute.call_args[0][1]
        assert "scoring_rounds" in insert_sql
        assert params[0] == 1
        assert params[1] == RoundState.COLLECTING.value


class TestUpdateRound:
    def test_updates_specified_fields(self):
        conn, cursor = _mock_conn()

        _update_round(conn, 1, status="SCORED", snapshot_hash="abc")

        sql = cursor.execute.call_args[0][0]
        assert "status" in sql
        assert "snapshot_hash" in sql
        conn.commit.assert_called_once()

    def test_no_op_when_no_fields(self):
        conn, cursor = _mock_conn()

        _update_round(conn, 1)
        cursor.execute.assert_not_called()


class TestFailRound:
    def test_sets_failed_status_and_error(self):
        conn, cursor = _mock_conn()

        _fail_round(conn, 1, "Something broke")

        sql = cursor.execute.call_args[0][0]
        values = cursor.execute.call_args[0][1]
        assert RoundState.FAILED.value in values
        assert "Something broke" in values


# ---------------------------------------------------------------------------
# Previous UNL lookup
# ---------------------------------------------------------------------------


class TestGetPreviousUNL:
    def test_returns_none_when_no_completed_rounds(self):
        conn, cursor = _mock_conn()
        cursor.fetchone.return_value = None

        result = _get_previous_unl(conn)
        assert result is None

    def test_returns_unl_from_audit_trail(self):
        conn = MagicMock()
        cursor1 = MagicMock()
        cursor2 = MagicMock()
        conn.cursor.side_effect = [cursor1, cursor2]

        cursor1.fetchone.return_value = ("somehash",)
        cursor2.fetchone.return_value = ({"unl": ["key_a", "key_b"], "alternates": []},)

        result = _get_previous_unl(conn)
        assert result == ["key_a", "key_b"]

    def test_returns_none_when_unl_file_missing(self):
        conn = MagicMock()
        cursor1 = MagicMock()
        cursor2 = MagicMock()
        conn.cursor.side_effect = [cursor1, cursor2]

        cursor1.fetchone.return_value = ("somehash",)
        cursor2.fetchone.return_value = None

        result = _get_previous_unl(conn)
        assert result is None


# ---------------------------------------------------------------------------
# Full pipeline — happy path
# ---------------------------------------------------------------------------


class TestRunRoundHappyPath:
    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.confirm_sequence")
    @patch("scoring_service.services.orchestrator.store_vl")
    @patch("scoring_service.services.orchestrator.reserve_next_sequence")
    @patch("scoring_service.services.orchestrator.generate_vl")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round")
    @patch("scoring_service.services.orchestrator._next_round_number")
    @patch("scoring_service.services.orchestrator.settings")
    def test_complete_round(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_prev_unl, mock_parse, mock_select, mock_gen_vl,
        mock_reserve, mock_store_vl, mock_confirm, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        mock_next_rn.return_value = 1
        mock_create.return_value = 42
        mock_prev_unl.return_value = None
        mock_parse.return_value = _make_scoring_result()
        mock_select.return_value = _make_unl_result()
        mock_reserve.return_value = 1
        mock_gen_vl.return_value = SAMPLE_VL

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            ("vhs_validators", {"data": True}),
            ("vhs_topology", {"nodes": []}),
        ]
        mock_get_db.return_value = conn

        mock_collector = MagicMock()
        mock_collector.collect.return_value = _mock_snapshot()
        mock_prompt = MagicMock()
        mock_prompt.build.return_value = ([{"role": "user", "content": "test"}], {"v001": "key"})
        mock_modal = MagicMock()
        mock_modal.score.return_value = '{"v001": {"score": 85}}'
        mock_rpc = MagicMock()
        mock_rpc.fetch_manifests.return_value = {"nHU_key_0": "manifest0", "nHU_key_1": "manifest1"}
        mock_ipfs = MagicMock()
        mock_ipfs.publish.return_value = "QmRootCID"
        mock_onchain = MagicMock()
        mock_onchain.publish.return_value = "TXHASH123"

        orchestrator = ScoringOrchestrator(
            collector=mock_collector,
            prompt_builder=mock_prompt,
            modal_client=mock_modal,
            rpc_client=mock_rpc,
            ipfs_publisher=mock_ipfs,
            onchain_publisher=mock_onchain,
        )

        result = orchestrator.run_round()

        assert result["status"] == RoundState.COMPLETE.value
        assert result["round_number"] == 1
        assert result["ipfs_cid"] == "QmRootCID"
        assert result["memo_tx_hash"] == "TXHASH123"
        assert result["vl_sequence"] == 1

        mock_collector.collect.assert_called_once_with(1, "testnet")
        mock_modal.score.assert_called_once()
        mock_rpc.fetch_manifests.assert_called_once()
        mock_ipfs.publish.assert_called_once()
        mock_onchain.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round")
    @patch("scoring_service.services.orchestrator._next_round_number")
    @patch("scoring_service.services.orchestrator.settings")
    def test_stops_after_selection(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_prev_unl, mock_parse, mock_select, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        mock_next_rn.return_value = 1
        mock_create.return_value = 42
        mock_prev_unl.return_value = None
        mock_parse.return_value = _make_scoring_result()
        mock_select.return_value = _make_unl_result()
        mock_get_db.return_value = MagicMock()

        mock_collector = MagicMock()
        mock_collector.collect.return_value = _mock_snapshot()
        mock_prompt = MagicMock()
        mock_prompt.build.return_value = ([], {"v001": "key"})
        mock_modal = MagicMock()
        mock_modal.score.return_value = '{"test": true}'
        mock_rpc = MagicMock()
        mock_ipfs = MagicMock()
        mock_onchain = MagicMock()

        orchestrator = ScoringOrchestrator(
            collector=mock_collector,
            prompt_builder=mock_prompt,
            modal_client=mock_modal,
            rpc_client=mock_rpc,
            ipfs_publisher=mock_ipfs,
            onchain_publisher=mock_onchain,
        )

        result = orchestrator.run_round(dry_run=True)

        assert result["status"] == RoundState.DRY_RUN_COMPLETE.value
        assert result["dry_run"] is True
        mock_rpc.fetch_manifests.assert_not_called()
        mock_ipfs.publish.assert_not_called()
        mock_onchain.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Per-state failure tests
# ---------------------------------------------------------------------------


class TestFailureAtEachState:
    def _make_orchestrator(self, **overrides):
        prompt = MagicMock()
        prompt.build.return_value = ([{"role": "user", "content": "test"}], {"v001": "key"})
        modal = MagicMock()
        modal.score.return_value = '{"v001": {"score": 85}}'
        defaults = {
            "collector": MagicMock(),
            "prompt_builder": prompt,
            "modal_client": modal,
            "rpc_client": MagicMock(),
            "ipfs_publisher": MagicMock(),
            "onchain_publisher": MagicMock(),
        }
        defaults.update(overrides)
        return ScoringOrchestrator(**defaults)

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_collecting(
        self, mock_settings, mock_next_rn, mock_create, mock_fail, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        mock_get_db.return_value = MagicMock()

        collector = MagicMock()
        collector.collect.side_effect = Exception("VHS unreachable")

        orchestrator = self._make_orchestrator(collector=collector)
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        mock_fail.assert_called_once()
        assert "COLLECTING" in mock_fail.call_args[0][2]

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_scored(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        modal = MagicMock()
        modal.score.return_value = None  # LLM returns nothing

        orchestrator = self._make_orchestrator(collector=collector, modal_client=modal)
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        mock_fail.assert_called_once()
        assert "SCORED" in mock_fail.call_args[0][2]

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_scored_incomplete(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_parse, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        mock_parse.return_value = _make_scoring_result(complete=False)
        modal = MagicMock()
        modal.score.return_value = '{"bad": "response"}'
        prompt = MagicMock()
        prompt.build.return_value = ([], {})

        orchestrator = self._make_orchestrator(
            collector=collector, modal_client=modal, prompt_builder=prompt,
        )
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        assert "Incomplete scoring" in mock_fail.call_args[0][2]

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_selected(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_prev_unl, mock_parse, mock_select, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        mock_parse.return_value = _make_scoring_result()
        mock_prev_unl.return_value = None
        mock_select.side_effect = Exception("Selection logic error")

        orchestrator = self._make_orchestrator(collector=collector)
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        assert "SELECTED" in mock_fail.call_args[0][2]

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.release_sequence")
    @patch("scoring_service.services.orchestrator.reserve_next_sequence")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_vl_signed_releases_sequence(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_prev_unl, mock_parse, mock_select,
        mock_reserve, mock_release, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        mock_parse.return_value = _make_scoring_result()
        mock_prev_unl.return_value = None
        mock_select.return_value = _make_unl_result()
        mock_reserve.return_value = 5
        rpc = MagicMock()
        rpc.fetch_manifests.side_effect = Exception("RPC timeout")

        orchestrator = self._make_orchestrator(collector=collector, rpc_client=rpc)
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        assert "VL_SIGNED" in mock_fail.call_args[0][2]
        mock_release.assert_called_once()

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.confirm_sequence")
    @patch("scoring_service.services.orchestrator.store_vl")
    @patch("scoring_service.services.orchestrator.reserve_next_sequence")
    @patch("scoring_service.services.orchestrator.generate_vl")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_ipfs(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_prev_unl, mock_parse, mock_select, mock_gen_vl,
        mock_reserve, mock_store_vl, mock_confirm, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        mock_parse.return_value = _make_scoring_result()
        mock_prev_unl.return_value = None
        mock_select.return_value = _make_unl_result()
        mock_reserve.return_value = 1
        mock_gen_vl.return_value = SAMPLE_VL
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {"key": "manifest"}
        ipfs = MagicMock()
        ipfs.publish.return_value = None  # IPFS failed

        orchestrator = self._make_orchestrator(
            collector=collector, rpc_client=rpc, ipfs_publisher=ipfs,
        )
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        assert "IPFS_PUBLISHED" in mock_fail.call_args[0][2]

    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.confirm_sequence")
    @patch("scoring_service.services.orchestrator.store_vl")
    @patch("scoring_service.services.orchestrator.reserve_next_sequence")
    @patch("scoring_service.services.orchestrator.generate_vl")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._fail_round")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=1)
    @patch("scoring_service.services.orchestrator.settings")
    def test_failure_at_onchain(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_fail, mock_prev_unl, mock_parse, mock_select, mock_gen_vl,
        mock_reserve, mock_store_vl, mock_confirm, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        mock_parse.return_value = _make_scoring_result()
        mock_prev_unl.return_value = None
        mock_select.return_value = _make_unl_result()
        mock_reserve.return_value = 1
        mock_gen_vl.return_value = SAMPLE_VL
        rpc = MagicMock()
        rpc.fetch_manifests.return_value = {"key": "manifest"}
        ipfs = MagicMock()
        ipfs.publish.return_value = "QmCID"
        onchain = MagicMock()
        onchain.publish.return_value = None  # On-chain failed

        orchestrator = self._make_orchestrator(
            collector=collector, rpc_client=rpc,
            ipfs_publisher=ipfs, onchain_publisher=onchain,
        )
        result = orchestrator.run_round()

        assert result["status"] == RoundState.FAILED.value
        assert "ONCHAIN_PUBLISHED" in mock_fail.call_args[0][2]


# ---------------------------------------------------------------------------
# Previous UNL passed to selector
# ---------------------------------------------------------------------------


class TestPreviousUNLIntegration:
    @patch("scoring_service.services.orchestrator.get_db")
    @patch("scoring_service.services.orchestrator.select_unl")
    @patch("scoring_service.services.orchestrator.parse_response")
    @patch("scoring_service.services.orchestrator._get_previous_unl")
    @patch("scoring_service.services.orchestrator._update_round")
    @patch("scoring_service.services.orchestrator._create_round", return_value=1)
    @patch("scoring_service.services.orchestrator._next_round_number", return_value=2)
    @patch("scoring_service.services.orchestrator.settings")
    def test_passes_previous_unl_to_selector(
        self, mock_settings, mock_next_rn, mock_create, mock_update,
        mock_prev_unl, mock_parse, mock_select, mock_get_db,
    ):
        mock_settings.pftl_network = "testnet"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        mock_get_db.return_value = conn

        mock_prev_unl.return_value = ["prev_key_a", "prev_key_b"]
        mock_parse.return_value = _make_scoring_result()
        mock_select.return_value = _make_unl_result()

        collector = MagicMock()
        collector.collect.return_value = _mock_snapshot()
        prompt = MagicMock()
        prompt.build.return_value = ([], {})
        modal = MagicMock()
        modal.score.return_value = '{"test": true}'

        orchestrator = ScoringOrchestrator(
            collector=collector,
            prompt_builder=prompt,
            modal_client=modal,
            rpc_client=MagicMock(),
            ipfs_publisher=MagicMock(),
            onchain_publisher=MagicMock(),
        )

        orchestrator.run_round(dry_run=True)

        mock_select.assert_called_once()
        call_args = mock_select.call_args
        assert call_args[0][1] == ["prev_key_a", "prev_key_b"]
