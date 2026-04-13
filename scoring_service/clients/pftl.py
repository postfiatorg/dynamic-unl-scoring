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
from typing import Optional

from ecpy.curves import Curve
from ecpy.keys import ECPrivateKey
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Memo, Payment
from xrpl.transaction import autofill, submit_and_wait
from xrpl.utils import str_to_hex
from xrpl.wallet import Wallet

from scoring_service.config import settings

logger = logging.getLogger(__name__)

PAYMENT_AMOUNT_DROPS = "1"


def wallet_from_hex_key(private_key_hex: str) -> Wallet:
    """Create a Wallet from a hex private key by deriving the public key."""
    private_key = private_key_hex.replace("0x", "").replace("0X", "")

    curve = Curve.get_curve("secp256k1")
    ec_private_key = ECPrivateKey(int(private_key, 16), curve)
    ec_public_key = ec_private_key.get_public_key()

    prefix = "02" if ec_public_key.W.y % 2 == 0 else "03"
    public_key = prefix + format(ec_public_key.W.x, "064x")

    return Wallet(public_key=public_key.upper(), private_key=private_key.upper())


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
            secret = self.wallet_secret.strip()
            if secret.startswith("s"):
                self._wallet = Wallet.from_seed(secret)
            else:
                self._wallet = wallet_from_hex_key(secret)
        return self._wallet

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
