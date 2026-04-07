"""On-chain memo publication service for scoring rounds.

Assembles a memo payload from round outputs and submits it to the
PFT Ledger via the PFTLClient. The memo anchors the round's IPFS CID
on-chain as a permanent, immutable receipt.
"""

import json
import logging

from scoring_service.clients.pftl import PFTLClient
from scoring_service.config import settings

logger = logging.getLogger(__name__)


def _build_memo_payload(
    ipfs_cid: str,
    vl_sequence: int,
) -> dict:
    return {
        "type": settings.scoring_memo_type,
        "ipfs_cid": ipfs_cid,
        "vl_sequence": vl_sequence,
    }


class OnChainPublisherService:
    """Publishes scoring round receipts on-chain."""

    def __init__(self, pftl_client: PFTLClient | None = None):
        self._pftl = pftl_client or PFTLClient()

    async def publish(
        self,
        ipfs_cid: str,
        vl_sequence: int,
    ) -> str | None:
        """Submit a scoring round memo transaction.

        Args:
            ipfs_cid: Root CID of the IPFS audit trail.
            vl_sequence: VL sequence number for this round.

        Returns:
            Transaction hash on success, or None on failure.
        """
        payload = _build_memo_payload(ipfs_cid, vl_sequence)
        memo_data = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        logger.info(
            "Submitting on-chain memo (vl_sequence=%d, CID=%s)",
            vl_sequence,
            ipfs_cid,
        )

        success, tx_hash, error = await self._pftl.submit_memo(memo_data)

        if success:
            logger.info(
                "On-chain memo published: vl_sequence=%d, tx=%s",
                vl_sequence,
                tx_hash,
            )
            return tx_hash

        logger.error(
            "On-chain memo failed for vl_sequence %d: %s",
            vl_sequence,
            error,
        )
        return None
