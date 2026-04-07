"""Tests for the on-chain memo publisher service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scoring_service.services.onchain_publisher import (
    OnChainPublisherService,
    _build_memo_payload,
)


class TestBuildMemoPayload:
    @patch("scoring_service.services.onchain_publisher.settings")
    def test_includes_all_fields(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        payload = _build_memo_payload(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
        )

        assert payload["type"] == "pf_dynamic_unl"
        assert payload["ipfs_cid"] == "QmTestCID"
        assert payload["vl_sequence"] == 42
        assert len(payload) == 3

    @patch("scoring_service.services.onchain_publisher.settings")
    def test_uses_memo_type_from_settings(self, mock_settings):
        mock_settings.scoring_memo_type = "custom_memo_type"

        payload = _build_memo_payload("QmCID", 1)
        assert payload["type"] == "custom_memo_type"


class TestPublish:
    @pytest.mark.asyncio
    async def test_returns_tx_hash_on_success(self):
        mock_pftl = MagicMock()
        mock_pftl.submit_memo = AsyncMock(return_value=(True, "TXHASH123", None))

        service = OnChainPublisherService(pftl_client=mock_pftl)
        tx_hash = await service.publish(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
        )

        assert tx_hash == "TXHASH123"
        mock_pftl.submit_memo.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        mock_pftl = MagicMock()
        mock_pftl.submit_memo = AsyncMock(return_value=(False, None, "tecNO_DST"))

        service = OnChainPublisherService(pftl_client=mock_pftl)
        tx_hash = await service.publish(
            ipfs_cid="QmTestCID",
            vl_sequence=42,
        )

        assert tx_hash is None

    @pytest.mark.asyncio
    @patch("scoring_service.services.onchain_publisher.settings")
    async def test_submits_compact_json(self, mock_settings):
        mock_settings.scoring_memo_type = "pf_dynamic_unl"

        mock_pftl = MagicMock()
        mock_pftl.submit_memo = AsyncMock(return_value=(True, "TXHASH", None))

        service = OnChainPublisherService(pftl_client=mock_pftl)
        await service.publish(
            ipfs_cid="QmCID",
            vl_sequence=1,
        )

        call_args = mock_pftl.submit_memo.call_args[0]
        memo_data = call_args[0]
        parsed = json.loads(memo_data)
        assert parsed["ipfs_cid"] == "QmCID"
        assert parsed["vl_sequence"] == 1
        assert " " not in memo_data

    @pytest.mark.asyncio
    async def test_does_not_pass_explicit_memo_type(self):
        mock_pftl = MagicMock()
        mock_pftl.submit_memo = AsyncMock(return_value=(True, "TXHASH", None))

        service = OnChainPublisherService(pftl_client=mock_pftl)
        await service.publish(
            ipfs_cid="QmCID",
            vl_sequence=1,
        )

        call_args = mock_pftl.submit_memo.call_args
        assert len(call_args[0]) == 1  # only memo_data, no memo_type
