"""On-chain memo publication service for scoring rounds.

Assembles a memo payload from round outputs and submits it to the
PFT Ledger via the PFTLClient. The memo anchors the round's final bundle CID
on-chain as a permanent, immutable receipt.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from scoring_service.clients.pftl import PFTLClient
from scoring_service.config import settings
from scoring_service.services.commit_reveal import (
    ROUND_ANNOUNCEMENT_TYPE,
    build_round_announcement,
    canonical_json_bytes,
    compute_round_windows,
    round_announcement_payload,
)

logger = logging.getLogger(__name__)


def _build_memo_payload(
    final_bundle_cid: str,
    vl_sequence: int,
    round_number: int,
    memo_type: str,
) -> dict:
    return {
        "type": memo_type,
        "final_bundle_cid": final_bundle_cid,
        "vl_sequence": vl_sequence,
        "round_number": round_number,
    }


class OnChainPublisherService:
    """Publishes scoring round receipts on-chain."""

    def __init__(self, pftl_client: PFTLClient | None = None):
        self._pftl = pftl_client or PFTLClient()

    def publish(
        self,
        final_bundle_cid: str,
        vl_sequence: int,
        round_number: int,
        memo_type: str | None = None,
    ) -> str | None:
        """Submit a scoring round memo transaction.

        Args:
            final_bundle_cid: Root CID of the final IPFS audit trail bundle.
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
        payload = _build_memo_payload(
            final_bundle_cid,
            vl_sequence,
            round_number,
            resolved_memo_type,
        )
        memo_data = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        logger.info(
            "Submitting on-chain memo (type=%s, round=%d, vl_sequence=%d, CID=%s)",
            resolved_memo_type,
            round_number,
            vl_sequence,
            final_bundle_cid,
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

    def publish_round_announcement(
        self,
        *,
        round_number: int,
        network: str,
        input_package_cid: str,
        input_package_hash: str,
        input_frozen_at: datetime,
        commit_window_seconds: int,
        reveal_window_seconds: int,
        reveal_gap_seconds: int = 0,
        now: datetime | None = None,
    ) -> str | None:
        """Submit the on-chain round-announcement memo for a frozen round.

        Derives the commit/reveal windows from the configured durations,
        anchored at emission time, builds the canonical announcement payload,
        and submits it from the publisher wallet with MemoType
        ROUND_ANNOUNCEMENT_TYPE. Returns the transaction hash, or None on
        failure.
        """
        anchor = now or datetime.now(timezone.utc)
        commit_opens, commit_closes, reveal_opens, reveal_closes = compute_round_windows(
            input_frozen_at=input_frozen_at,
            anchor=anchor,
            commit_window=timedelta(seconds=commit_window_seconds),
            reveal_window=timedelta(seconds=reveal_window_seconds),
            reveal_gap=timedelta(seconds=reveal_gap_seconds),
        )
        announcement = build_round_announcement(
            network=network,
            round_number=round_number,
            input_package_cid=input_package_cid,
            input_package_hash=input_package_hash,
            commit_opens_at=commit_opens,
            commit_closes_at=commit_closes,
            reveal_opens_at=reveal_opens,
            reveal_closes_at=reveal_closes,
        )
        memo_data = canonical_json_bytes(
            round_announcement_payload(announcement)
        ).decode("utf-8")

        logger.info(
            "Submitting round announcement (type=%s, round=%d, network=%s)",
            ROUND_ANNOUNCEMENT_TYPE,
            round_number,
            network,
        )

        success, tx_hash, error = self._pftl.submit_memo(
            memo_data,
            memo_type=ROUND_ANNOUNCEMENT_TYPE,
        )

        if success:
            logger.info(
                "Round announcement published: round=%d, tx=%s",
                round_number,
                tx_hash,
            )
            return tx_hash

        logger.error(
            "Round announcement failed for round=%d: %s",
            round_number,
            error,
        )
        return None
