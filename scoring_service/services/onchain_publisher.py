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
    round_number: int,
    memo_type: str,
) -> dict:
    return {
        "type": memo_type,
        "ipfs_cid": ipfs_cid,
        "vl_sequence": vl_sequence,
        "round_number": round_number,
    }


class OnChainPublisherService:
    """Publishes scoring round receipts on-chain."""

    def __init__(self, pftl_client: PFTLClient | None = None):
        self._pftl = pftl_client or PFTLClient()

    def publish(
        self,
        ipfs_cid: str,
        vl_sequence: int,
        round_number: int,
        memo_type: str | None = None,
    ) -> str | None:
        """Submit a scoring round memo transaction.

        Args:
            ipfs_cid: Root CID of the IPFS audit trail.
            vl_sequence: VL sequence number for this round.
            round_number: Scoring round number. Embedded in the memo so
                third parties decoding the memo can resolve it to a round
                without a vl_sequence lookup.
            memo_type: Override of the memo `type` field. Defaults to
                `settings.scoring_memo_type` (automated rounds). Admin
                override paths pass `settings.scoring_memo_type_override`.

        Returns:
            Transaction hash on success, or None on failure.
        """
        resolved_memo_type = memo_type or settings.scoring_memo_type
        payload = _build_memo_payload(ipfs_cid, vl_sequence, round_number, resolved_memo_type)
        memo_data = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        logger.info(
            "Submitting on-chain memo (type=%s, round=%d, vl_sequence=%d, CID=%s)",
            resolved_memo_type,
            round_number,
            vl_sequence,
            ipfs_cid,
        )

        success, tx_hash, error = self._pftl.submit_memo(memo_data)

        if success:
            logger.info(
                "On-chain memo published: type=%s, round=%d, vl_sequence=%d, tx=%s",
                resolved_memo_type,
                round_number,
                vl_sequence,
                tx_hash,
            )
            return tx_hash

        logger.error(
            "On-chain memo failed for round=%d vl_sequence=%d: %s",
            round_number,
            vl_sequence,
            error,
        )
        return None
