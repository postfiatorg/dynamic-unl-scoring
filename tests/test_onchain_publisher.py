"""Tests for the on-chain memo publisher service."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scoring_service.services.commit_reveal import (
    ROUND_ANNOUNCEMENT_TYPE,
    validate_round_announcement,
)
from scoring_service.services.onchain_publisher import (
    OnChainPublisherService,
    _build_memo_payload,
)


class TestBuildMemoPayload:
    def test_includes_all_fields(self):
        payload = _build_memo_payload(
            final_bundle_cid="QmTestCID",
            vl_sequence=42,
            round_number=7,
            memo_type="pf_dynamic_unl",
        )

        assert payload["type"] == "pf_dynamic_unl"
        assert payload["final_bundle_cid"] == "QmTestCID"
        assert payload["vl_sequence"] == 42
        assert payload["round_number"] == 7
        assert len(payload) == 4

    def test_accepts_override_memo_type(self):
        payload = _build_memo_payload(
            final_bundle_cid="QmCID",
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
            final_bundle_cid="QmTestCID",
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
            final_bundle_cid="QmTestCID",
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
            final_bundle_cid="QmCID",
            vl_sequence=1,
            round_number=99,
        )

        call_args = mock_pftl.submit_memo.call_args[0]
        memo_data = call_args[0]
        parsed = json.loads(memo_data)
        assert parsed["final_bundle_cid"] == "QmCID"
        assert "ipfs_cid" not in parsed
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
            final_bundle_cid="QmCID",
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
            final_bundle_cid="QmCID",
            vl_sequence=1,
            round_number=42,
        )

        memo_data = mock_pftl.submit_memo.call_args[0][0]
        parsed = json.loads(memo_data)
        assert parsed["type"] == "pf_dynamic_unl"


class TestPublishRoundAnnouncement:
    def _service(self, submit_result):
        mock_pftl = MagicMock()
        mock_pftl.submit_memo.return_value = submit_result
        return OnChainPublisherService(pftl_client=mock_pftl), mock_pftl

    def _publish_kwargs(self, **overrides):
        kwargs = {
            "round_number": 123,
            "network": "testnet",
            "input_package_cid": "Qm" + "A" * 44,
            "input_package_hash": "d" * 64,
            "input_frozen_at": datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc),
            "commit_window_seconds": 1800,
            "reveal_window_seconds": 1800,
            "reveal_gap_seconds": 0,
            "now": datetime(2026, 5, 25, 0, 10, tzinfo=timezone.utc),
        }
        kwargs.update(overrides)
        return kwargs

    def test_submits_announcement_memo_type_and_decoded_payload(self):
        service, mock_pftl = self._service((True, "TXHASH123", None))

        tx_hash = service.publish_round_announcement(**self._publish_kwargs())

        assert tx_hash == "TXHASH123"
        (memo_data,) = mock_pftl.submit_memo.call_args[0]
        assert mock_pftl.submit_memo.call_args[1]["memo_type"] == ROUND_ANNOUNCEMENT_TYPE

        announcement = validate_round_announcement(json.loads(memo_data))
        assert announcement.round_number == 123
        assert announcement.network == "testnet"
        assert announcement.input_package_hash == "d" * 64
        assert announcement.input_package_cid == "Qm" + "A" * 44
        assert announcement.commit_opens_at == datetime(2026, 5, 25, 0, 10, tzinfo=timezone.utc)
        assert announcement.commit_closes_at == datetime(2026, 5, 25, 0, 40, tzinfo=timezone.utc)
        assert announcement.reveal_opens_at == datetime(2026, 5, 25, 0, 40, tzinfo=timezone.utc)
        assert announcement.reveal_closes_at == datetime(2026, 5, 25, 1, 10, tzinfo=timezone.utc)

    def test_payload_excludes_type_field(self):
        service, mock_pftl = self._service((True, "TX", None))

        service.publish_round_announcement(**self._publish_kwargs())

        (memo_data,) = mock_pftl.submit_memo.call_args[0]
        assert "type" not in json.loads(memo_data)

    def test_returns_none_on_submission_failure(self):
        service, _ = self._service((False, None, "tecUNFUNDED"))

        assert service.publish_round_announcement(**self._publish_kwargs()) is None
