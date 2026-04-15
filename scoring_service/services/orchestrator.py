"""Scoring orchestrator — state machine that drives a full scoring round.

Wires all pipeline services together in sequence: data collection, LLM
scoring, UNL selection, VL signing, IPFS publication, and on-chain memo.
Tracks round state in the scoring_rounds table. Failed rounds are not
resumed, fresh round starts on the next trigger.
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum

from scoring_service.clients.github_pages import GitHubPagesClient
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
    VL_DISTRIBUTED = "VL_DISTRIBUTED"
    ONCHAIN_PUBLISHED = "ONCHAIN_PUBLISHED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    DRY_RUN_COMPLETE = "DRY_RUN_COMPLETE"


TERMINAL_STATES = frozenset({RoundState.COMPLETE, RoundState.FAILED, RoundState.DRY_RUN_COMPLETE})


def _cleanup_stale_rounds(conn) -> int:
    """Mark any rounds stuck in non-terminal states as FAILED.

    Returns the number of rounds cleaned up.
    """
    terminal = tuple(s.value for s in TERMINAL_STATES)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE scoring_rounds
        SET status = %s, error_message = %s, completed_at = %s
        WHERE status NOT IN %s
        """,
        (
            RoundState.FAILED.value,
            "Round abandoned — service restarted",
            datetime.now(timezone.utc),
            terminal,
        ),
    )
    cleaned = cursor.rowcount
    conn.commit()
    cursor.close()
    if cleaned > 0:
        logger.warning("Cleaned up %d stale round(s)", cleaned)
    return cleaned


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


def _create_override_round(
    conn,
    round_number: int,
    override_type: str,
    override_reason: str,
) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scoring_rounds (round_number, status, started_at, override_type, override_reason)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            round_number,
            RoundState.VL_SIGNED.value,
            datetime.now(timezone.utc),
            override_type,
            override_reason,
        ),
    )
    round_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    logger.info(
        "Created override round %d (id=%d, type=%s)",
        round_number,
        round_id,
        override_type,
    )
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
        github_pages_client: GitHubPagesClient | None = None,
    ):
        self._collector = collector or DataCollectorService()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._modal = modal_client or ModalClient()
        self._rpc = rpc_client or RPCClient()
        self._ipfs_publisher = ipfs_publisher or IPFSPublisherService()
        self._onchain_publisher = onchain_publisher or OnChainPublisherService()
        self._github_pages = github_pages_client or GitHubPagesClient()

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
        _cleanup_stale_rounds(conn)
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
            signed_vl = generate_vl(
                unl_result.unl,
                manifests,
                vl_sequence,
                effective_lookahead_hours=settings.vl_effective_lookahead_hours,
            )
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

        # --- Step 6: VL_DISTRIBUTED ---
        # Commits the signed VL to the GitHub Pages repo that backs
        # `postfiat.org/{env}_vl.json`. Runs before the on-chain memo so that
        # a distribution failure does not burn a transaction that would claim
        # a VL was distributed when it was not.
        try:
            vl_json = json.dumps(signed_vl, separators=(",", ":"))
            commit_message = (
                f"Scoring round {round_number} — VL sequence {vl_sequence}"
            )
            github_pages_commit_url = self._github_pages.publish(
                content=vl_json,
                commit_message=commit_message,
            )
            _update_round(
                conn, round_id,
                status=RoundState.VL_DISTRIBUTED.value,
                github_pages_commit_url=github_pages_commit_url,
            )
            result["github_pages_commit_url"] = github_pages_commit_url
        except Exception as exc:
            _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 7: ONCHAIN_PUBLISHED ---
        try:
            tx_hash = self._onchain_publisher.publish(
                ipfs_cid=ipfs_cid,
                vl_sequence=vl_sequence,
                round_number=round_number,
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

    def run_override_round(
        self,
        master_keys: list[str],
        reason: str,
        override_type: str,
        effective_lookahead_hours: int | None = None,
        expiration_days: int | None = None,
    ) -> dict:
        """Publish a VL using a foundation-specified UNL.

        Bypasses COLLECTING, SCORED, and SELECTED — the UNL has been
        supplied directly by the caller. Runs VL_SIGNED, IPFS_PUBLISHED,
        VL_DISTRIBUTED, and ONCHAIN_PUBLISHED identically to an
        automated round except: the IPFS audit trail carries an
        `override` block with type and reason, the on-chain memo uses
        the `pf_dynamic_unl_override` memo type, and the synthetic
        round row records `override_type` and `override_reason`.

        Args:
            master_keys: Ordered validator master keys to include in the VL.
            reason: Operator-supplied free-text justification. Persisted in
                IPFS metadata and the round row; not on-chain.
            override_type: Either ``"custom"`` (arbitrary UNL) or
                ``"rollback"`` (UNL sourced from a historical round).
            effective_lookahead_hours: VL activation lookahead in hours.
                Defaults to ``settings.vl_effective_lookahead_hours``.
            expiration_days: VL expiration in days. Defaults to
                ``settings.vl_expiration_days``.

        Returns:
            Dict with round metadata: round_id, round_number, status,
            override_type, override_reason, vl_sequence, ipfs_cid,
            github_pages_commit_url, and memo_tx_hash on success.
        """
        conn = get_db()
        _cleanup_stale_rounds(conn)
        round_number = _next_round_number(conn)
        round_id = _create_override_round(conn, round_number, override_type, reason)

        lookahead = (
            effective_lookahead_hours
            if effective_lookahead_hours is not None
            else settings.vl_effective_lookahead_hours
        )

        result: dict = {
            "round_id": round_id,
            "round_number": round_number,
            "override_type": override_type,
            "override_reason": reason,
        }

        # --- Step 4: VL_SIGNED (override path starts here) ---
        vl_sequence = None
        try:
            vl_sequence = reserve_next_sequence(conn)
            manifests = self._rpc.fetch_manifests(master_keys)
            signed_vl = generate_vl(
                master_keys,
                manifests,
                vl_sequence,
                effective_lookahead_hours=lookahead,
                expiration_days=expiration_days,
            )
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
            ipfs_cid = self._ipfs_publisher.publish_override(
                round_number=round_number,
                master_keys=master_keys,
                signed_vl=signed_vl,
                override_type=override_type,
                override_reason=reason,
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

        # --- Step 6: VL_DISTRIBUTED ---
        try:
            vl_json = json.dumps(signed_vl, separators=(",", ":"))
            commit_message = (
                f"Override round {round_number} ({override_type}) — VL sequence {vl_sequence}"
            )
            github_pages_commit_url = self._github_pages.publish(
                content=vl_json,
                commit_message=commit_message,
            )
            _update_round(
                conn, round_id,
                status=RoundState.VL_DISTRIBUTED.value,
                github_pages_commit_url=github_pages_commit_url,
            )
            result["github_pages_commit_url"] = github_pages_commit_url
        except Exception as exc:
            _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 7: ONCHAIN_PUBLISHED (override memo type) ---
        try:
            tx_hash = self._onchain_publisher.publish(
                ipfs_cid=ipfs_cid,
                vl_sequence=vl_sequence,
                round_number=round_number,
                memo_type=settings.scoring_memo_type_override,
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
            "Override round %d complete: type=%s, vl_sequence=%d, cid=%s, tx=%s",
            round_number,
            override_type,
            vl_sequence,
            ipfs_cid,
            tx_hash,
        )
        return result
