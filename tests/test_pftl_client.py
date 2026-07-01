"""Tests for the PFTL blockchain client."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from scoring_service.clients.pftl import (
    PAYMENT_AMOUNT_DROPS,
    PFTLClient,
    PFTLPrunedLedgerError,
    _earliest_complete_ledger,
    _is_pruned_ledger,
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


class TestAccountTx:
    def _client(self):
        return PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_result_on_success(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"transactions": [], "marker": "M1"}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        result = self._client().account_tx("rPublisher", ledger_index_min=10, limit=50)

        assert result["marker"] == "M1"
        request = mock_rpc.request.call_args[0][0]
        assert request.account == "rPublisher"
        assert request.ledger_index_min == 10
        assert request.forward is True

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_on_failed_call(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"error_message": "actNotFound"}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(RuntimeError, match="account_tx failed") as exc:
            self._client().account_tx("rPublisher")
        # A generic failure is not misreported as a pruned-ledger condition.
        assert not isinstance(exc.value, PFTLPrunedLedgerError)

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_pruned_on_lgr_idx_malformed_name(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {
            "error": "lgrIdxMalformed",
            "error_message": "Ledger index malformed.",
        }
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(PFTLPrunedLedgerError):
            self._client().account_tx("rPublisher", ledger_index_min=100)

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_pruned_on_error_code_58(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"error_code": 58, "error_message": "Ledger index malformed."}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(PFTLPrunedLedgerError):
            self._client().account_tx("rPublisher", ledger_index_min=100)


class TestEarliestValidatedLedger:
    def _client(self):
        return PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_earliest_from_complete_ledgers(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"info": {"complete_ledgers": "2300169-2366222"}}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        assert self._client().earliest_validated_ledger() == 2300169

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_uses_first_range_when_comma_separated(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {
            "info": {"complete_ledgers": "2300169-2310000,2350000-2366222"}
        }
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        assert self._client().earliest_validated_ledger() == 2300169

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_on_empty_range(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"info": {"complete_ledgers": "empty"}}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(RuntimeError, match="complete_ledgers"):
            self._client().earliest_validated_ledger()

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_on_server_info_failure(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"error_message": "noNetwork"}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(RuntimeError, match="server_info failed"):
            self._client().earliest_validated_ledger()


class TestPrunedLedgerHelpers:
    def test_is_pruned_ledger_by_error_name(self):
        assert _is_pruned_ledger({"error": "lgrIdxMalformed"}) is True

    def test_is_pruned_ledger_by_error_code(self):
        assert _is_pruned_ledger({"error_code": 58}) is True

    def test_is_pruned_ledger_false_for_other_error(self):
        assert _is_pruned_ledger({"error": "actNotFound"}) is False

    def test_is_pruned_ledger_false_for_non_dict(self):
        assert _is_pruned_ledger("Ledger index malformed.") is False

    def test_earliest_complete_ledger_parses_single_range(self):
        assert _earliest_complete_ledger("100-200") == 100

    def test_earliest_complete_ledger_takes_first_of_multiple(self):
        assert _earliest_complete_ledger("100-150,180-200") == 100

    def test_earliest_complete_ledger_raises_on_empty(self):
        with pytest.raises(RuntimeError):
            _earliest_complete_ledger("empty")
        with pytest.raises(RuntimeError):
            _earliest_complete_ledger("")

    def test_earliest_complete_ledger_raises_on_missing_value(self):
        # server_info without info/complete_ledgers yields None — fail closed.
        with pytest.raises(RuntimeError):
            _earliest_complete_ledger(None)

    def test_earliest_complete_ledger_raises_on_non_numeric(self):
        with pytest.raises(RuntimeError, match="not a ledger range"):
            _earliest_complete_ledger("abc-def")


class TestPublisherAddress:
    def test_returns_classic_address(self):
        client = PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )
        assert client.publisher_address == client.wallet.classic_address
        assert client.publisher_address.startswith("r")


class TestLatestValidatedLedgerCloseTime:
    def _client(self):
        return PFTLClient(
            rpc_url="https://rpc.example.com",
            wallet_secret=TEST_PRIVATE_KEY,
            memo_destination="rAddr",
            network_id=2025,
        )

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_returns_datetime(self, mock_rpc_cls):
        from datetime import datetime

        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {"ledger": {"close_time": 773000000}}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        assert isinstance(self._client().latest_validated_ledger_close_time(), datetime)

    @patch("scoring_service.clients.pftl.JsonRpcClient")
    def test_raises_on_failure(self, mock_rpc_cls):
        mock_rpc = MagicMock()
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"error_message": "noNetwork"}
        mock_rpc.request.return_value = mock_response
        mock_rpc_cls.return_value = mock_rpc

        with pytest.raises(RuntimeError, match="ledger request failed"):
            self._client().latest_validated_ledger_close_time()
