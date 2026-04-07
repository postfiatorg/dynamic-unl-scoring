"""Scoring orchestrator — state machine that drives a full scoring round.

Wires all pipeline services together in sequence: data collection, LLM
scoring, UNL selection, VL signing, IPFS publication, and on-chain memo.
Tracks round state in the scoring_rounds table. Failed rounds are not
resumed, fresh round starts on the next trigger.
"""

import logging
from datetime import datetime, timezone
from enum import Enum

from scoring_service.clients.modal import ModalClient
from scoring_service.clients.rpc import RPCClient
from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.services.collector import DataCollectorService
from scoring_service.services.ipfs_publisher import IPFSPublisherService
from scoring_service.services.onchain_publisher import OnChainPublisherService
from scoring_service.services.prompt_builder import PromptBuilder
from scoring_service.services.response_parser import parse_response
from scoring_service.services.unl_selector import select_unl
from scoring_service.services.vl_generator import generate_vl
from scoring_service.services.vl_sequence import (
    confirm_sequence,
    release_sequence,
    reserve_next_sequence,
    store_vl,
)

logger = logging.getLogger(__name__)


class RoundState(str, Enum):
    COLLECTING = "COLLECTING"
    SCORED = "SCORED"
    SELECTED = "SELECTED"
    VL_SIGNED = "VL_SIGNED"
    IPFS_PUBLISHED = "IPFS_PUBLISHED"
    ONCHAIN_PUBLISHED = "ONCHAIN_PUBLISHED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    DRY_RUN_COMPLETE = "DRY_RUN_COMPLETE"


def _next_round_number(conn) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(round_number), 0) FROM scoring_rounds")
    current_max = cursor.fetchone()[0]
    cursor.close()
    return current_max + 1


def _create_round(conn, round_number: int) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scoring_rounds (round_number, status, started_at)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (round_number, RoundState.COLLECTING.value, datetime.now(timezone.utc)),
    )
    round_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    logger.info("Created scoring round %d (id=%d)", round_number, round_id)
    return round_id


def _update_round(conn, round_id: int, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [round_id]
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE scoring_rounds SET {set_clause} WHERE id = %s",
        values,
    )
    conn.commit()
    cursor.close()


def _fail_round(conn, round_id: int, error: str) -> None:
    _update_round(
        conn,
        round_id,
        status=RoundState.FAILED.value,
        error_message=error,
        completed_at=datetime.now(timezone.utc),
    )
    logger.error("Round %d failed: %s", round_id, error)


def _get_previous_unl(conn) -> list[str] | None:
    """Fetch the UNL from the last successfully completed round."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT snapshot_hash FROM scoring_rounds
        WHERE status = %s
        ORDER BY round_number DESC
        LIMIT 1
        """,
        (RoundState.COMPLETE.value,),
    )
    row = cursor.fetchone()
    cursor.close()

    if row is None:
        return None

    # The UNL is stored in the audit trail files from the IPFS publisher
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT content FROM audit_trail_files
        WHERE round_number = (
            SELECT round_number FROM scoring_rounds
            WHERE status = %s
            ORDER BY round_number DESC
            LIMIT 1
        )
        AND file_path = 'unl.json'
        """,
        (RoundState.COMPLETE.value,),
    )
    row = cursor.fetchone()
    cursor.close()

    if row is None:
        return None

    return row[0].get("unl", [])


class ScoringOrchestrator:
    """Drives a full scoring round through the pipeline."""

    def __init__(
        self,
        collector: DataCollectorService | None = None,
        prompt_builder: PromptBuilder | None = None,
        modal_client: ModalClient | None = None,
        rpc_client: RPCClient | None = None,
        ipfs_publisher: IPFSPublisherService | None = None,
        onchain_publisher: OnChainPublisherService | None = None,
    ):
        self._collector = collector or DataCollectorService()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._modal = modal_client or ModalClient()
        self._rpc = rpc_client or RPCClient()
        self._ipfs_publisher = ipfs_publisher or IPFSPublisherService()
        self._onchain_publisher = onchain_publisher or OnChainPublisherService()

    def run_round(self, dry_run: bool = False) -> dict:
        """Execute a full scoring round.

        Args:
            dry_run: If True, run collect/score/select but skip
                VL signing, IPFS publication, and on-chain memo.

        Returns:
            Dict with round metadata: round_id, round_number, status,
            and any outputs produced (snapshot_hash, ipfs_cid, etc).
        """
        conn = get_db()
        round_number = _next_round_number(conn)
        round_id = _create_round(conn, round_number)
        network = settings.pftl_network

        result = {
            "round_id": round_id,
            "round_number": round_number,
            "dry_run": dry_run,
        }

        # --- Step 1: COLLECTING ---
        try:
            snapshot = self._collector.collect(round_number, network)
            raw_evidence = self._load_raw_evidence(conn, round_number)
            _update_round(
                conn, round_id,
                status=RoundState.COLLECTING.value,
                snapshot_hash=snapshot.content_hash(),
            )
            result["snapshot_hash"] = snapshot.content_hash()
        except Exception as exc:
            _fail_round(conn, round_id, f"COLLECTING: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 2: SCORED ---
        try:
            messages, validator_id_map = self._prompt_builder.build(snapshot)
            raw_response = self._modal.score(messages)
            if raw_response is None:
                raise RuntimeError("LLM returned no response")
            scoring_result = parse_response(raw_response, validator_id_map)
            if not scoring_result.complete:
                raise RuntimeError(
                    f"Incomplete scoring: {'; '.join(scoring_result.errors)}"
                )
            _update_round(conn, round_id, status=RoundState.SCORED.value)
        except Exception as exc:
            _fail_round(conn, round_id, f"SCORED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 3: SELECTED ---
        try:
            previous_unl = _get_previous_unl(conn)
            unl_result = select_unl(scoring_result, previous_unl)
            _update_round(conn, round_id, status=RoundState.SELECTED.value)
            result["validator_count"] = len(unl_result.unl)
        except Exception as exc:
            _fail_round(conn, round_id, f"SELECTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Dry run exits here ---
        if dry_run:
            _update_round(
                conn, round_id,
                status=RoundState.DRY_RUN_COMPLETE.value,
                completed_at=datetime.now(timezone.utc),
            )
            conn.close()
            result["status"] = RoundState.DRY_RUN_COMPLETE.value
            logger.info("Dry run complete for round %d", round_number)
            return result

        # --- Step 4: VL_SIGNED ---
        vl_sequence = None
        try:
            vl_sequence = reserve_next_sequence(conn)
            manifests = self._rpc.fetch_manifests(unl_result.unl)
            signed_vl = generate_vl(unl_result.unl, manifests, vl_sequence)
            store_vl(conn, signed_vl)
            confirm_sequence(conn, vl_sequence)
            conn.commit()
            _update_round(
                conn, round_id,
                status=RoundState.VL_SIGNED.value,
                vl_sequence=vl_sequence,
            )
            result["vl_sequence"] = vl_sequence
        except Exception as exc:
            if vl_sequence is not None:
                release_sequence(conn)
                conn.commit()
            _fail_round(conn, round_id, f"VL_SIGNED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 5: IPFS_PUBLISHED ---
        try:
            ipfs_cid = self._ipfs_publisher.publish(
                round_number=round_number,
                snapshot=snapshot,
                raw_evidence=raw_evidence,
                scoring_result=scoring_result,
                unl_result=unl_result,
                signed_vl=signed_vl,
                conn=conn,
            )
            if ipfs_cid is None:
                raise RuntimeError("IPFS pinning returned no CID")
            _update_round(
                conn, round_id,
                status=RoundState.IPFS_PUBLISHED.value,
                ipfs_cid=ipfs_cid,
            )
            result["ipfs_cid"] = ipfs_cid
        except Exception as exc:
            _fail_round(conn, round_id, f"IPFS_PUBLISHED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 6: ONCHAIN_PUBLISHED ---
        try:
            tx_hash = self._onchain_publisher.publish(
                ipfs_cid=ipfs_cid,
                vl_sequence=vl_sequence,
            )
            if tx_hash is None:
                raise RuntimeError("On-chain memo submission failed")
            _update_round(
                conn, round_id,
                status=RoundState.ONCHAIN_PUBLISHED.value,
                memo_tx_hash=tx_hash,
            )
            result["memo_tx_hash"] = tx_hash
        except Exception as exc:
            _fail_round(conn, round_id, f"ONCHAIN_PUBLISHED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- COMPLETE ---
        _update_round(
            conn, round_id,
            status=RoundState.COMPLETE.value,
            completed_at=datetime.now(timezone.utc),
        )
        conn.close()
        result["status"] = RoundState.COMPLETE.value
        logger.info(
            "Round %d complete: vl_sequence=%d, cid=%s, tx=%s",
            round_number,
            vl_sequence,
            ipfs_cid,
            tx_hash,
        )
        return result

    def _load_raw_evidence(self, conn, round_number: int) -> dict:
        """Load raw evidence from the database for IPFS publication."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT source, raw_data FROM raw_evidence WHERE round_number = %s",
            (round_number,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return {source: raw_data for source, raw_data in rows}
