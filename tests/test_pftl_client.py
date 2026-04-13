"""Tests for the PFTL blockchain client."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.clients.pftl import (
    PAYMENT_AMOUNT_DROPS,
    PFTLClient,
    wallet_from_hex_key,
)

# Known secp256k1 test key pair (not used on any real network)
TEST_PRIVATE_KEY = "00a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"


class TestWalletFromHexKey:
    def test_derives_valid_wallet(self):
        wallet = wallet_from_hex_key(TEST_PRIVATE_KEY)
        assert wallet.private_key is not None
        assert wallet.public_key is not None
        assert len(wallet.public_key) == 66  # compressed: 02/03 + 64 hex chars

    def test_public_key_starts_with_02_or_03(self):
        wallet = wallet_from_hex_key(TEST_PRIVATE_KEY)
        assert wallet.public_key[:2] in ("02", "03")

    def test_strips_0x_prefix(self):
        wallet_plain = wallet_from_hex_key(TEST_PRIVATE_KEY)
        wallet_prefixed = wallet_from_hex_key("0x" + TEST_PRIVATE_KEY)
        assert wallet_plain.public_key == wallet_prefixed.public_key

    def test_deterministic(self):
        wallet_a = wallet_from_hex_key(TEST_PRIVATE_KEY)
        wallet_b = wallet_from_hex_key(TEST_PRIVATE_KEY)
        assert wallet_a.public_key == wallet_b.public_key
        assert wallet_a.private_key == wallet_b.private_key

    def test_private_key_uppercased(self):
        wallet = wallet_from_hex_key("aabbccdd" * 8)
        assert wallet.private_key == wallet.private_key.upper()


class TestInit:
    @patch("scoring_service.clients.pftl.settings")
    def test_raises_when_rpc_url_missing(self, mock_settings):
        mock_settings.pftl_rpc_url = ""
        mock_settings.pftl_wallet_secret = "secret"
        mock_settings.pftl_memo_destination = "rAddr"
        mock_settings.pftl_network_id = 2025
        with pytest.raises(ValueError, match="PFTL_RPC_URL is required"):
            PFTLClient()

    @patch("scoring_service.clients.pftl.settings")
    def test_raises_when_wallet_secret_missing(self, mock_settings):
        mock_settings.pftl_rpc_url = "https://rpc.example.com"
        mock_settings.pftl_wallet_secret = ""
        mock_settings.pftl_memo_destination = "rAddr"
        mock_settings.pftl_network_id = 2025
        with pytest.raises(ValueError, match="PFTL_WALLET_SECRET is required"):
            PFTLClient()

    @patch("scoring_service.clients.pftl.settings")
    def test_raises_when_memo_destination_missing(self, mock_settings):
        mock_settings.pftl_rpc_url = "https://rpc.example.com"
        mock_settings.pftl_wallet_secret = "secret"
        mock_settings.pftl_memo_destination = ""
        mock_settings.pftl_network_id = 2025
        with pytest.raises(ValueError, match="PFTL_MEMO_DESTINATION is required"):
            PFTLClient()

    def test_uses_explicit_params(self):
        client = PFTLClient(
            rpc_url="https://custom.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rCustomAddr",
            network_id=2024,
        )
        assert client.rpc_url == "https://custom.example.com"
        assert client.memo_destination == "rCustomAddr"
        assert client.network_id == 2024


class TestWalletProperty:
    def test_creates_wallet_from_hex_key(self):
        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )
        wallet = client.wallet
        assert wallet.public_key[:2] in ("02", "03")

    def test_wallet_is_cached(self):
        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )
        assert client.wallet is client.wallet


class TestSubmitMemo:
    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_hash_on_success(self, mock_rpc_cls, mock_autofill, mock_submit):
        mock_autofill.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"hash": "ABC123TXHASH"}
        mock_submit.return_value = mock_response

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        success, tx_hash, error = client.submit_memo('{"round": 1}')

        assert success is True
        assert tx_hash == "ABC123TXHASH"
        assert error is None

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_error_on_failed_tx(self, mock_rpc_cls, mock_autofill, mock_submit):
        mock_autofill.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"engine_result_message": "tecNO_DST"}
        mock_submit.return_value = mock_response

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        success, tx_hash, error = client.submit_memo('{"round": 1}')

        assert success is False
        assert tx_hash is None
        assert error == "tecNO_DST"

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_error_on_exception(self, mock_rpc_cls, mock_autofill, mock_submit):
        mock_autofill.side_effect = Exception("Connection refused")

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        success, tx_hash, error = client.submit_memo('{"round": 1}')

        assert success is False
        assert tx_hash is None
        assert error is not None and "Connection refused" in error

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_builds_correct_payment(self, mock_rpc_cls, mock_autofill, mock_submit):
        mock_autofill.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"hash": "TXHASH"}
        mock_submit.return_value = mock_response

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rTestDestination",
            network_id=2024,
        )

        client.submit_memo('{"data": "test"}', "pf_dynamic_unl")

        tx_arg = mock_autofill.call_args[0][0]
        assert tx_arg.amount == PAYMENT_AMOUNT_DROPS
        assert tx_arg.destination == "rTestDestination"
        assert tx_arg.network_id == 2024
        assert len(tx_arg.memos) == 1


class TestSubmitMemoEventLoopSafety:
    """Regression tests for the asyncio event loop conflict.

    The scheduler runs inside FastAPI's lifespan (active event loop).
    xrpl-py's autofill/submit_and_wait internally call asyncio.run(),
    which fails if an event loop is already running. The ThreadPoolExecutor
    isolation in submit_memo() prevents this by always executing the
    xrpl-py calls in a clean thread.
    """

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_works_from_plain_thread(self, mock_rpc_cls, mock_autofill, mock_submit):
        """Manual trigger path: no event loop in the calling thread."""
        mock_autofill.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"hash": "PLAIN_THREAD_TX"}
        mock_submit.return_value = mock_response

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        success, tx_hash, error = client.submit_memo('{"round": 1}')

        assert success is True
        assert tx_hash == "PLAIN_THREAD_TX"
        mock_autofill.assert_called_once()
        mock_submit.assert_called_once()

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_works_from_active_event_loop(self, mock_rpc_cls, mock_autofill, mock_submit):
        """Scheduler path: event loop already running in the calling thread.

        This is the exact scenario that caused round 5 to fail with
        'asyncio.run() cannot be called from a running event loop'.
        """
        mock_autofill.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"hash": "EVENT_LOOP_TX"}
        mock_submit.return_value = mock_response

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        async def call_from_async_context():
            return client.submit_memo('{"round": 2}')

        success, tx_hash, error = asyncio.run(call_from_async_context())

        assert success is True
        assert tx_hash == "EVENT_LOOP_TX"
        mock_autofill.assert_called_once()
        mock_submit.assert_called_once()

    @patch("scoring_service.clients.pftl.submit_and_wait")
    @patch("scoring_service.clients.pftl.autofill")
    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_error_handling_preserved_in_thread_pool(self, mock_rpc_cls, mock_autofill, mock_submit):
        """Errors from xrpl-py inside the thread pool still surface correctly."""
        mock_autofill.side_effect = Exception("Network timeout")

        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

        async def call_from_async_context():
            return client.submit_memo('{"round": 3}')

        success, tx_hash, error = asyncio.run(call_from_async_context())

        assert success is False
        assert tx_hash is None
        assert error is not None and "Network timeout" in error
