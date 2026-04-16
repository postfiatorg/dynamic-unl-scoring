"""Tests for the on-chain memo publisher service."""

import json
from unittest.mock import MagicMock, patch

from scoring_service.services.onchain_publisher import (
    OnChainPublisherService,
    _build_memo_payload,
)


class TestBuildMemoPayload:
    def test_includes_all_fields(self):
        payload = _build_memo_payload(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
            round_number=7,
            memo_type="pf_dynamic_unl",
        )

        assert payload["type"] == "pf_dynamic_unl"
        assert payload["ipfs_cid"] == "QmTestCID"
        assert payload["vl_sequence"] == 42
        assert payload["round_number"] == 7
        assert len(payload) == 4

    def test_accepts_override_memo_type(self):
        payload = _build_memo_payload(
            ipfs_cid="QmCID",
            vl_sequence=1,
            round_number=1,
            memo_type="pf_dynamic_unl_override",
        )
        assert payload["type"] == "pf_dynamic_unl_override"


class TestPublish:
    @patch("scoring_service.services.onchain_publisher.settings")
    def test_returns_tx_hash_on_success(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = (True, "TXHASH123", None)

        service = OnChainPublisherService(pftl_client=mock_pftl)
        tx_hash = service.publish(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
            round_number=7,
        )

        assert tx_hash == "TXHASH123"
        mock_pftl.submit_memo.assert_called_once()

    @patch("scoring_service.services.onchain_publisher.settings")
    def test_returns_none_on_failure(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = (False, None, "tecNO_DST")

        service = OnChainPublisherService(pftl_client=mock_pftl)
        tx_hash = service.publish(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
            round_number=7,
        )

        assert tx_hash is None

    @patch("scoring_service.services.onchain_publisher.settings")
    def test_submits_compact_json_with_round_number(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = (True, "TXHASH", None)

        service = OnChainPublisherService(pftl_client=mock_pftl)
        service.publish(
            ipfs_cid="QmCID",
            vl_sequence=1,
            round_number=99,
        )

        call_args = mock_pftl.submit_memo.call_args[0]
        memo_data = call_args[0]
        parsed = json.loads(memo_data)
        assert parsed["ipfs_cid"] == "QmCID"
        assert parsed["vl_sequence"] == 1
        assert parsed["round_number"] == 99
        assert parsed["type"] == "pf_dynamic_unl"
        assert " " not in memo_data

    @patch("scoring_service.services.onchain_publisher.settings")
    def test_override_memo_type_overrides_default(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = (True, "TXHASH", None)

        service = OnChainPublisherService(pftl_client=mock_pftl)
        service.publish(
            ipfs_cid="QmCID",
            vl_sequence=1,
            round_number=42,
            memo_type="pf_dynamic_unl_override",
        )

        memo_data = mock_pftl.submit_memo.call_args[0][0]
        parsed = json.loads(memo_data)
        assert parsed["type"] == "pf_dynamic_unl_override"

    @patch("scoring_service.services.onchain_publisher.settings")
    def test_default_memo_type_used_when_not_specified(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = (True, "TXHASH", None)

        service = OnChainPublisherService(pftl_client=mock_pftl)
        service.publish(
            ipfs_cid="QmCID",
            vl_sequence=1,
            round_number=42,
        )

        memo_data = mock_pftl.submit_memo.call_args[0][0]
        parsed = json.loads(memo_data)
        assert parsed["type"] == "pf_dynamic_unl"
