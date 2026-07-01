"""PFTL blockchain client for on-chain memo transactions.

Submits Payment transactions with memo attachments to the PFT Ledger.
Wallet is derived from a hex private key using secp256k1 curve math.

Transaction submission is isolated in a ThreadPoolExecutor so xrpl-py's
internal asyncio.run() never conflicts with an already-running event
loop. This allows the same code path to work from both the manual
trigger (plain thread, no event loop) and the scheduler (FastAPI
lifespan, asyncio event loop already active).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from ecpy.curves import Curve
from ecpy.keys import ECPrivateKey
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import AccountInfo, AccountTx, Ledger, ServerInfo
from xrpl.models.transactions import Memo, Payment
from xrpl.transaction import autofill, submit_and_wait
from xrpl.utils import ripple_time_to_datetime, str_to_hex
from xrpl.wallet import Wallet

from scoring_service.config import settings

logger = logging.getLogger(__name__)

PAYMENT_AMOUNT_DROPS = "1"
DROPS_PER_PFT = 1_000_000

# rippled's malformed-ledger-index error (name and numeric code). For an
# account_tx with a valid integer lower bound and max == -1 it means the lower
# bound predates the node's retained history — i.e. those ledgers were pruned.
LGR_IDX_MALFORMED_ERROR = "lgrIdxMalformed"
LGR_IDX_MALFORMED_CODE = 58


class PFTLPrunedLedgerError(RuntimeError):
    """Raised when an ``account_tx`` lower bound is below the node's retained
    history (``lgrIdxMalformed``) — the requested ledgers have been pruned off a
    non-archive node. A ``RuntimeError`` subclass so existing generic handling
    still catches it, but distinct so the watcher can recover by clamping the
    scan floor forward rather than treating the pass as a hard failure."""


def _is_pruned_ledger(result: object) -> bool:
    """True when an account_tx error means the lower bound predates retained
    history (``lgrIdxMalformed`` / error code 58).

    Code 58 is rippled's general malformed-ledger-index error — it also covers a
    non-integer index or ``min > max``. It unambiguously means "pruned" only
    because the watcher always sends a valid integer lower bound with
    ``max == -1``; do not reuse this helper for calls without that guarantee.
    """
    if not isinstance(result, dict):
        return False
    return (
        result.get("error") == LGR_IDX_MALFORMED_ERROR
        or result.get("error_code") == LGR_IDX_MALFORMED_CODE
    )


def _earliest_complete_ledger(value: object) -> int:
    """Earliest validated ledger the node still retains, parsed from the
    ``complete_ledgers`` range string (e.g. ``"2300169-2366222"``; ranges are
    comma-separated and the first one's start is the earliest available)."""
    if not isinstance(value, str) or not value.strip() or value.strip() == "empty":
        raise RuntimeError(
            f"server_info has no usable complete_ledgers range: {value!r}"
        )
    low = value.split(",")[0].split("-")[0].strip()
    try:
        return int(low)
    except ValueError as exc:
        raise RuntimeError(
            f"complete_ledgers is not a ledger range: {value!r}"
        ) from exc


def wallet_from_hex_key(private_key_hex: str) -> Wallet:
    """Create a Wallet from a hex private key by deriving the public key."""
    private_key = private_key_hex.replace("0x", "").replace("0X", "")

    curve = Curve.get_curve("secp256k1")
    ec_private_key = ECPrivateKey(int(private_key, 16), curve)
    ec_public_key = ec_private_key.get_public_key()

    prefix = "02" if ec_public_key.W.y % 2 == 0 else "03"
    public_key = prefix + format(ec_public_key.W.x, "064x")

    return Wallet(public_key=public_key.upper(), private_key=private_key.upper())


def wallet_from_secret(secret: str) -> Wallet:
    """Derive an xrpl Wallet from a seed (s...) or a hex private key."""
    secret = secret.strip()
    if secret.startswith("s"):
        return Wallet.from_seed(secret)
    return wallet_from_hex_key(secret)


class PFTLClient:
    """Sync client for PFTL chain transactions."""

    def __init__(
        self,
        rpc_url: str | None = None,
        wallet_secret: str | None = None,
        memo_destination: str | None = None,
        network_id: int | None = None,
    ):
        self.rpc_url = rpc_url or settings.pftl_rpc_url
        self.wallet_secret = wallet_secret or settings.pftl_wallet_secret
        self.memo_destination = memo_destination or settings.pftl_memo_destination
        self.network_id = network_id or settings.pftl_network_id

        if not self.rpc_url:
            raise ValueError("PFTL_RPC_URL is required but not configured")
        if not self.wallet_secret:
            raise ValueError("PFTL_WALLET_SECRET is required but not configured")
        if not self.memo_destination:
            raise ValueError("PFTL_MEMO_DESTINATION is required but not configured")

        self._client: Optional[JsonRpcClient] = None
        self._wallet: Optional[Wallet] = None

    @property
    def client(self) -> JsonRpcClient:
        if self._client is None:
            self._client = JsonRpcClient(self.rpc_url)
        return self._client

    @property
    def wallet(self) -> Wallet:
        if self._wallet is None:
            self._wallet = wallet_from_secret(self.wallet_secret)
        return self._wallet

    @property
    def publisher_address(self) -> str:
        """Public classic (r...) address of the publisher wallet.

        This is the account validator commit and reveal memos are addressed
        to, so it is the single account the convergence watcher scans.
        """
        return self.wallet.classic_address

    def account_tx(
        self,
        account: str,
        *,
        ledger_index_min: int = -1,
        ledger_index_max: int = -1,
        limit: int = 200,
        marker: object | None = None,
        forward: bool = True,
    ) -> dict:
        """Fetch a page of an account's validated transaction history.

        Thin wrapper over the `account_tx` RPC. `forward=True` returns the
        page oldest-first so a watcher can advance a ledger cursor; `marker`
        pages through the remaining results. Raises RuntimeError if the RPC
        call fails.
        """
        request = AccountTx(
            account=account,
            ledger_index_min=ledger_index_min,
            ledger_index_max=ledger_index_max,
            limit=limit,
            marker=marker,
            forward=forward,
        )
        response = self.client.request(request)
        if not response.is_successful():
            if _is_pruned_ledger(response.result):
                raise PFTLPrunedLedgerError(
                    f"account_tx lower bound {ledger_index_min} is below the "
                    f"node's retained history for {account}: {response.result}"
                )
            error = response.result.get("error_message") or response.result.get(
                "error", "unknown error"
            )
            raise RuntimeError(f"account_tx failed: {error}")
        return response.result

    def earliest_validated_ledger(self) -> int:
        """The earliest validated ledger the RPC node still retains.

        Read from ``server_info``'s ``complete_ledgers`` range so the watcher can
        clamp a stale cursor forward when it has fallen below a pruning node's
        retained history.
        """
        response = self.client.request(ServerInfo())
        if not response.is_successful():
            error = response.result.get("error_message") or response.result.get(
                "error", "unknown error"
            )
            raise RuntimeError(f"server_info failed: {error}")
        complete = (response.result.get("info") or {}).get("complete_ledgers")
        return _earliest_complete_ledger(complete)

    def submit_memo(
        self,
        memo_data: str,
        memo_type: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Submit a Payment transaction with a memo attachment.

        Args:
            memo_data: JSON string to attach as memo data.
            memo_type: Memo type identifier. Defaults to settings.scoring_memo_type.

        Returns:
            Tuple of (success, tx_hash, error_message).
        """
        memo_type = memo_type or settings.scoring_memo_type
        try:
            memo = Memo(
                memo_type=str_to_hex(memo_type),
                memo_data=str_to_hex(memo_data),
            )

            tx = Payment(
                account=self.wallet.classic_address,
                destination=self.memo_destination,
                amount=PAYMENT_AMOUNT_DROPS,
                network_id=self.network_id,
                memos=[memo],
            )

            rpc_client = self.client
            wallet = self.wallet

            def _execute():
                tx_autofilled = autofill(tx, rpc_client)
                return submit_and_wait(tx_autofilled, rpc_client, wallet)

            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(_execute).result()

            if response.is_successful():
                tx_hash = response.result.get("hash")
                logger.info("PFTL memo transaction successful: %s", tx_hash)
                return True, tx_hash, None

            error = response.result.get("engine_result_message", "Unknown error")
            logger.error("PFTL memo transaction failed: %s", error)
            return False, None, error

        except Exception as exc:
            logger.error("PFTL memo transaction error: %s", exc)
            return False, None, str(exc)

    def latest_validated_ledger_close_time(self) -> datetime:
        """Return the close time of the latest validated ledger.

        This is consensus-agreed network time, used to judge protocol
        deadlines (e.g. when a round's seal grace has elapsed) consistently
        with how commit/reveal windows are evaluated. Raises RuntimeError if
        the RPC call fails.
        """
        response = self.client.request(Ledger(ledger_index="validated"))
        if not response.is_successful():
            error = response.result.get("error_message") or response.result.get(
                "error", "unknown error"
            )
            raise RuntimeError(f"ledger request failed: {error}")
        close_time = response.result["ledger"]["close_time"]
        return ripple_time_to_datetime(int(close_time))

    def get_balance_drops(self) -> int:
        """Return the publisher wallet's balance in drops.

        Raises RuntimeError if the RPC call fails or the account is not
        found on the ledger.
        """
        request = AccountInfo(
            account=self.wallet.classic_address,
            ledger_index="validated",
        )
        response = self.client.request(request)
        if not response.is_successful():
            error = response.result.get("error_message") or response.result.get(
                "error", "unknown error"
            )
            raise RuntimeError(f"account_info failed: {error}")
        balance_str = response.result["account_data"]["Balance"]
        return int(balance_str)
