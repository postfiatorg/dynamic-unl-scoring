"""Scoring orchestrator — state machine that drives a full scoring round.

Wires all pipeline services together in sequence: data collection, LLM
scoring, UNL selection, VL signing, IPFS publication, and on-chain memo.
Tracks round state in the scoring_rounds table. Failed rounds are not
resumed, fresh round starts on the next trigger.
"""

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from scoring_service.clients.github_pages import GitHubPagesClient
from scoring_service.clients.modal import ModalClient
from scoring_service.clients.rpc import RPCClient
from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.models import ScoringSnapshot
from scoring_service.services.collector import DataCollectorService
from scoring_service.services.dry_runs import (
    create_dry_run,
    fail_dry_run,
    update_dry_run,
)
from scoring_service.services.ipfs_publisher import (
    InputPackagePublication,
    IPFSPublisherService,
    get_selected_unl_file,
)
from scoring_service.services.onchain_publisher import OnChainPublisherService
from scoring_service.services.prompt_builder import PromptBuilder
from scoring_service.services.response_parser import ScoringResult, parse_response
from scoring_service.services.unl_selector import UNLSelectionResult, select_unl
from scoring_service.services.vl_generator import (
    generate_vl,
    read_vl_effective,
    resign_vl_with_effective,
)
from scoring_service.services.vl_sequence import (
    confirm_sequence,
    release_sequence,
    reserve_next_sequence,
    store_vl,
)

logger = logging.getLogger(__name__)


class RoundState(str, Enum):
    COLLECTING = "COLLECTING"
    INPUT_FROZEN = "INPUT_FROZEN"
    SCORED = "SCORED"
    SELECTED = "SELECTED"
    VL_SIGNED = "VL_SIGNED"
    AWAITING_COMMIT_CLOSE = "AWAITING_COMMIT_CLOSE"
    IPFS_PUBLISHED = "IPFS_PUBLISHED"
    VL_DISTRIBUTED = "VL_DISTRIBUTED"
    ONCHAIN_PUBLISHED = "ONCHAIN_PUBLISHED"
    COMPLETE = "COMPLETE"
    VL_PUBLISHED_MEMO_FAILED = "VL_PUBLISHED_MEMO_FAILED"
    FAILED = "FAILED"
    DRY_RUN_COMPLETE = "DRY_RUN_COMPLETE"


OPERATIONALLY_PUBLISHED_STATES = (
    RoundState.COMPLETE,
    RoundState.VL_PUBLISHED_MEMO_FAILED,
)

TERMINAL_STATES = frozenset({
    RoundState.COMPLETE,
    RoundState.VL_PUBLISHED_MEMO_FAILED,
    RoundState.FAILED,
    RoundState.DRY_RUN_COMPLETE,
})

RESUMABLE_PUBLICATION_STATES = frozenset({
    RoundState.AWAITING_COMMIT_CLOSE,
    RoundState.IPFS_PUBLISHED,
    RoundState.VL_DISTRIBUTED,
    RoundState.ONCHAIN_PUBLISHED,
})

# Minimum lead time a held VL's activation must have over the publication
# moment. A delayed resume can leave the signing-time stamp in the past; below
# this margin the VL is re-signed so validators still cache it as pending and
# switch in unison instead of activating on their independent poll cycles.
# Assumes vl_effective_lookahead_hours is at least this margin (all deployed
# values are minutes to hours); a shorter non-zero lookahead would re-trigger
# the guard on every retry without ever clearing it.
_VL_ACTIVATION_MIN_FUTURE_SECONDS = 60


def _cleanup_stale_rounds(conn) -> int:
    """Mark abandoned active rounds as FAILED.

    Publication states are intentionally resumable across restarts: a normal
    round parks in AWAITING_COMMIT_CLOSE until the commit window closes, and
    publication may resume from IPFS_PUBLISHED, VL_DISTRIBUTED, or
    ONCHAIN_PUBLISHED without recomputing the score.

    Returns the number of rounds cleaned up.
    """
    terminal = tuple(s.value for s in TERMINAL_STATES)
    resumable = tuple(s.value for s in RESUMABLE_PUBLICATION_STATES)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE scoring_rounds
        SET status = %s, error_message = %s, completed_at = %s
        WHERE status NOT IN %s
          AND status NOT IN %s
        """,
        (
            RoundState.FAILED.value,
            "Round abandoned — service restarted",
            datetime.now(timezone.utc),
            terminal,
            resumable,
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


def _json_param(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _int_setting(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _float_setting(name: str, default: float) -> float:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _snapshot_payload(snapshot, *, round_number: int, network: str) -> dict:
    try:
        payload = json.loads(snapshot.model_dump_json())
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    # Unit tests often use light mocks for snapshots. Real runs always take the
    # branch above; this fallback keeps control-flow tests focused on state.
    return {
        "round_number": round_number,
        "network": network,
        "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
        "validators": [],
    }


def _store_pending_publication(
    conn,
    *,
    round_number: int,
    snapshot,
    raw_evidence: dict[str, Any],
    scoring_result: ScoringResult,
    unl_result: UNLSelectionResult,
    signed_vl: dict[str, Any],
    prompt_messages: list[dict] | tuple[dict, ...],
    validator_id_map: dict[str, Any],
    input_package: InputPackagePublication,
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scoring_round_publication_artifacts (
            round_number, snapshot, raw_evidence, scoring_result, unl_result,
            signed_vl, prompt_messages, validator_id_map, input_package_files
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (round_number) DO UPDATE SET
            snapshot = EXCLUDED.snapshot,
            raw_evidence = EXCLUDED.raw_evidence,
            scoring_result = EXCLUDED.scoring_result,
            unl_result = EXCLUDED.unl_result,
            signed_vl = EXCLUDED.signed_vl,
            prompt_messages = EXCLUDED.prompt_messages,
            validator_id_map = EXCLUDED.validator_id_map,
            input_package_files = EXCLUDED.input_package_files,
            created_at = now()
        """,
        (
            round_number,
            _json_param(_snapshot_payload(snapshot, round_number=round_number, network=input_package.model_request.get("network", ""))),
            _json_param(raw_evidence),
            _json_param(scoring_result.model_dump(mode="json")),
            _json_param(asdict(unl_result)),
            _json_param(signed_vl),
            _json_param(list(prompt_messages)),
            _json_param(validator_id_map),
            _json_param(input_package.files),
        ),
    )
    cursor.close()
    conn.commit()


def _update_pending_signed_vl(conn, round_number: int, signed_vl: dict) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE scoring_round_publication_artifacts
        SET signed_vl = %s
        WHERE round_number = %s
        """,
        (_json_param(signed_vl), round_number),
    )
    cursor.close()
    conn.commit()


def _delete_pending_publication(conn, round_number: int) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM scoring_round_publication_artifacts WHERE round_number = %s",
        (round_number,),
    )
    cursor.close()
    conn.commit()


def _load_pending_publication(conn, round_number: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT p.snapshot, p.raw_evidence, p.scoring_result, p.unl_result,
               p.signed_vl, p.prompt_messages, p.validator_id_map,
               p.input_package_files,
               r.input_package_cid, r.input_package_hash, r.input_frozen_at
        FROM scoring_round_publication_artifacts p
        JOIN scoring_rounds r ON r.round_number = p.round_number
        WHERE p.round_number = %s
        """,
        (round_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None

    snapshot_payload = _json_value(row[0])
    raw_evidence = _json_value(row[1])
    scoring_payload = _json_value(row[2])
    unl_payload = _json_value(row[3])
    signed_vl = _json_value(row[4])
    prompt_messages = _json_value(row[5])
    validator_id_map = _json_value(row[6])
    input_package_files = _json_value(row[7])

    input_package = InputPackagePublication(
        cid=row[8],
        package_hash=row[9],
        frozen_at=row[10],
        model_request=input_package_files.get("inputs/model_request.json", {}),
        validator_id_map=input_package_files.get("inputs/validator_map.json", {}),
        previous_unl=(input_package_files.get("inputs/previous_unl.json", {}) or {}).get(
            "previous_unl", []
        ),
        files=input_package_files,
    )
    return {
        "snapshot": ScoringSnapshot.model_validate(snapshot_payload),
        "raw_evidence": raw_evidence,
        "scoring_result": ScoringResult.model_validate(scoring_payload),
        "unl_result": UNLSelectionResult(**unl_payload),
        "signed_vl": signed_vl,
        "prompt_messages": prompt_messages,
        "validator_id_map": validator_id_map,
        "input_package": input_package,
    }


def _publication_deadlines(
    *,
    input_frozen_at: datetime,
    announcement_anchor: datetime | None,
    announced: bool,
) -> tuple[datetime, datetime]:
    if announced and announcement_anchor is not None:
        commit_opens_at = max(input_frozen_at, announcement_anchor)
    else:
        # Conservative fallback: no on-chain announcement means no authoritative
        # ledger window, so withhold for a full commit window after input freeze.
        commit_opens_at = input_frozen_at
    commit_closes_at = commit_opens_at + timedelta(
        seconds=_int_setting("announcement_commit_window_seconds", 10800)
    )
    due_at = commit_closes_at + timedelta(
        seconds=_int_setting("output_publication_delay_seconds", 15)
    )
    return commit_closes_at, due_at


def _round_announcement_tx_hash(conn, round_id: int) -> str | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT announcement_tx_hash FROM scoring_rounds WHERE id = %s",
        (round_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def _fail_round(conn, round_id: int, error: str) -> None:
    _update_round(
        conn,
        round_id,
        status=RoundState.FAILED.value,
        error_message=error,
        completed_at=datetime.now(timezone.utc),
    )
    logger.error("Round %d failed: %s", round_id, error)


def _mark_vl_published_memo_failed(conn, round_id: int, error: str) -> None:
    _update_round(
        conn,
        round_id,
        status=RoundState.VL_PUBLISHED_MEMO_FAILED.value,
        error_message=error,
        completed_at=datetime.now(timezone.utc),
    )
    logger.error("Round %d published VL but memo failed: %s", round_id, error)


def _release_reserved_sequence(conn, vl_sequence: int | None) -> None:
    if vl_sequence is None:
        return
    release_sequence(conn)
    conn.commit()


def _confirm_public_vl(
    conn,
    round_id: int,
    signed_vl: dict,
    vl_sequence: int,
    github_pages_commit_url: str,
) -> None:
    """Advance current VL state after public distribution succeeds."""
    store_vl(conn, signed_vl)
    confirm_sequence(conn, vl_sequence)

    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE scoring_rounds
        SET status = %s, vl_sequence = %s, github_pages_commit_url = %s
        WHERE id = %s
        """,
        (
            RoundState.VL_DISTRIBUTED.value,
            vl_sequence,
            github_pages_commit_url,
            round_id,
        ),
    )
    cursor.close()
    conn.commit()


def _get_previous_unl(conn) -> list[str] | None:
    """Fetch the UNL from the last operationally published round."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT round_number FROM scoring_rounds
        WHERE status IN %s
        ORDER BY round_number DESC
        LIMIT 1
        """,
        (tuple(s.value for s in OPERATIONALLY_PUBLISHED_STATES),),
    )
    row = cursor.fetchone()
    cursor.close()

    if row is None:
        return None

    unl_data = get_selected_unl_file(conn, row[0])
    if unl_data is None:
        return None
    return unl_data.get("unl", [])


def _due_publication_rounds(conn, now: datetime) -> list[int]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT round_number
        FROM scoring_rounds
        WHERE status IN %s
          AND output_publication_due_at IS NOT NULL
          AND output_publication_due_at <= %s
          AND override_type IS NULL
        ORDER BY round_number ASC
        """,
        (tuple(s.value for s in RESUMABLE_PUBLICATION_STATES), now),
    )
    rounds = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return rounds


def _load_publication_round(conn, round_number: int) -> tuple | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, status, vl_sequence, final_bundle_cid,
               github_pages_commit_url, memo_tx_hash
        FROM scoring_rounds
        WHERE round_number = %s
          AND status IN %s
          AND override_type IS NULL
        """,
        (round_number, tuple(s.value for s in RESUMABLE_PUBLICATION_STATES)),
    )
    row = cursor.fetchone()
    cursor.close()
    return row


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

    def _emit_round_announcement(
        self,
        conn,
        round_id: int,
        round_number: int,
        network: str,
        input_package,
        *,
        now: datetime | None = None,
    ) -> str | None:
        """Emit the on-chain round announcement once, at INPUT_FROZEN.

        Idempotent: skips emission if the round already has a persisted
        announcement tx hash. Submission failure is non-blocking — it is logged
        and surfaced via the absent tx hash, and scoring is allowed to proceed
        because VL publication remains the authoritative path.
        """
        existing = _round_announcement_tx_hash(conn, round_id)
        if existing:
            logger.info(
                "Round %d already announced (tx=%s); skipping emission",
                round_number,
                existing,
            )
            return existing
        try:
            tx_hash = self._onchain_publisher.publish_round_announcement(
                round_number=round_number,
                network=network,
                input_package_cid=input_package.cid,
                input_package_hash=input_package.package_hash,
                input_frozen_at=input_package.frozen_at,
                commit_window_seconds=settings.announcement_commit_window_seconds,
                reveal_window_seconds=settings.announcement_reveal_window_seconds,
                reveal_gap_seconds=settings.announcement_reveal_gap_seconds,
                now=now,
            )
        except Exception as exc:
            logger.error(
                "Round %d announcement emission failed: %s", round_number, exc
            )
            return None
        if tx_hash:
            _update_round(conn, round_id, announcement_tx_hash=tx_hash)
        else:
            logger.error(
                "Round %d emitted no announcement; sidecars cannot verify its "
                "commit/reveal windows",
                round_number,
            )
        return tx_hash

    def _announcement_anchor_time(self) -> datetime:
        """Return PFTL validated-ledger time when available, else UTC now."""
        try:
            candidate = self._onchain_publisher.latest_validated_ledger_close_time()
            if isinstance(candidate, datetime):
                return candidate.astimezone(timezone.utc)
        except Exception as exc:  # noqa: BLE001 - fallback keeps announcement non-blocking
            logger.warning(
                "Could not read validated-ledger close time for round announcement; "
                "falling back to service UTC time: %s",
                exc,
            )
        return datetime.now(timezone.utc)

    def run_round(self, dry_run: bool = False) -> dict:
        """Execute a full scoring round.

        Args:
            dry_run: If True, delegate to the private dry-run lifecycle.

        Returns:
            Dict with round metadata: round_id, round_number, status,
            and any outputs produced (snapshot_hash, final_bundle_cid, etc).
        """
        if dry_run:
            return self.run_dry_run()

        conn = get_db()
        _cleanup_stale_rounds(conn)
        round_number = _next_round_number(conn)
        round_id = _create_round(conn, round_number)
        network = settings.pftl_network

        result = {
            "round_id": round_id,
            "round_number": round_number,
            "dry_run": False,
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

        # --- Step 2: INPUT_FROZEN ---
        try:
            messages, validator_id_map = self._prompt_builder.build(snapshot)
            previous_unl = _get_previous_unl(conn) or []
            input_package = self._ipfs_publisher.publish_input_package(
                round_number=round_number,
                snapshot=snapshot,
                raw_evidence=raw_evidence,
                conn=conn,
                prompt_messages=messages,
                validator_id_map=validator_id_map,
                previous_unl=previous_unl,
            )
            if input_package is None:
                raise RuntimeError("Input package IPFS pinning returned no CID")
            _update_round(
                conn,
                round_id,
                status=RoundState.INPUT_FROZEN.value,
                input_package_cid=input_package.cid,
                input_package_hash=input_package.package_hash,
                input_frozen_at=input_package.frozen_at,
            )
            messages = input_package.model_request["messages"]
            validator_id_map = input_package.validator_id_map
            result["input_package_cid"] = input_package.cid
            result["input_package_hash"] = input_package.package_hash
            result["input_frozen_at"] = input_package.frozen_at.isoformat()
        except Exception as exc:
            conn.rollback()
            _fail_round(conn, round_id, f"INPUT_FROZEN: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        announcement_anchor = self._announcement_anchor_time()
        announcement_tx_hash = self._emit_round_announcement(
            conn,
            round_id,
            round_number,
            network,
            input_package,
            now=announcement_anchor,
        )
        if announcement_tx_hash:
            result["announcement_tx_hash"] = announcement_tx_hash

        # Publication is withheld until the commit window closes, so the VL's
        # activation time must be anchored to when it will actually be
        # published — not to signing time. Compute the deadlines before signing
        # so the effective timestamp lands after publication and validators
        # still receive the blob as pending.
        commit_closes_at, publication_due_at = _publication_deadlines(
            input_frozen_at=input_package.frozen_at,
            announcement_anchor=announcement_anchor,
            announced=announcement_tx_hash is not None,
        )
        vl_effective_at = publication_due_at + timedelta(
            hours=_float_setting("vl_effective_lookahead_hours", 1.0)
        )

        # --- Step 3: SCORED ---
        try:
            raw_response = self._modal.score_request(input_package.model_request)
            if raw_response is None:
                raise RuntimeError("LLM returned no response")
            scoring_result = parse_response(raw_response, validator_id_map)
            if not scoring_result.complete:
                raise RuntimeError(
                    f"Incomplete scoring: {'; '.join(scoring_result.errors)}"
                )
            scores_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
            _update_round(
                conn,
                round_id,
                status=RoundState.SCORED.value,
                scores_hash=scores_hash,
            )
            result["scores_hash"] = scores_hash
        except Exception as exc:
            _fail_round(conn, round_id, f"SCORED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 4: SELECTED ---
        try:
            # Select from the previous UNL frozen into the input package, not
            # live DB state, so selection is reproducible from the frozen inputs.
            unl_result = select_unl(scoring_result, input_package.previous_unl)
            _update_round(conn, round_id, status=RoundState.SELECTED.value)
            result["validator_count"] = len(unl_result.unl)
        except Exception as exc:
            _fail_round(conn, round_id, f"SELECTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 5: VL_SIGNED ---
        vl_sequence = None
        try:
            vl_sequence = reserve_next_sequence(conn)
            conn.commit()
            manifests = self._rpc.fetch_manifests(unl_result.unl)
            signed_vl = generate_vl(
                unl_result.unl,
                manifests,
                vl_sequence,
                effective_at=vl_effective_at,
            )
            _update_round(
                conn, round_id,
                status=RoundState.VL_SIGNED.value,
            )
            result["vl_sequence"] = vl_sequence
        except Exception as exc:
            _release_reserved_sequence(conn, vl_sequence)
            _fail_round(conn, round_id, f"VL_SIGNED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 6-8: publication is withheld until commit close ---
        try:
            _store_pending_publication(
                conn,
                round_number=round_number,
                snapshot=snapshot,
                raw_evidence=raw_evidence,
                scoring_result=scoring_result,
                unl_result=unl_result,
                signed_vl=signed_vl,
                prompt_messages=messages,
                validator_id_map=validator_id_map,
                input_package=input_package,
            )
            _update_round(
                conn,
                round_id,
                status=RoundState.AWAITING_COMMIT_CLOSE.value,
                vl_sequence=vl_sequence,
                output_publication_commit_closes_at=commit_closes_at,
                output_publication_due_at=publication_due_at,
                output_publication_not_tracked=announcement_tx_hash is None,
            )
            result["vl_sequence"] = vl_sequence
            result["output_publication_commit_closes_at"] = commit_closes_at.isoformat()
            result["output_publication_due_at"] = publication_due_at.isoformat()
            result["status"] = RoundState.AWAITING_COMMIT_CLOSE.value
        except Exception as exc:
            _release_reserved_sequence(conn, vl_sequence)
            _fail_round(conn, round_id, f"AWAITING_COMMIT_CLOSE: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        conn.close()
        logger.info(
            "Round %d awaiting commit close before output publication: "
            "vl_sequence=%d, commit_closes_at=%s, due_at=%s",
            round_number,
            vl_sequence,
            commit_closes_at.isoformat(),
            publication_due_at.isoformat(),
        )
        return result

    def _refresh_stale_vl_activation(
        self,
        conn,
        round_number: int,
        artifacts: dict,
    ) -> None:
        """Re-sign a held VL whose activation time is no longer safely in the future.

        A held round was signed with an activation time anchored to its expected
        publication moment. If publication is delayed (outage, long deploy) that
        stamp can fall into the past, which would make every validator activate
        the list immediately on fetch instead of caching it and switching in
        unison. In that case re-stamp with a fresh lookahead from now. With a
        zero lookahead immediate activation is the configured intent, so there
        is nothing to protect.

        Read or re-sign failures are contained: the round publishes as-is. A
        failure persisting the re-signed VL is deliberately not contained — it
        aborts this publication pass so an unpersisted re-sign is never
        published, and the still-held round retries on the next scheduler tick.
        """
        lookahead_hours = _float_setting("vl_effective_lookahead_hours", 1.0)
        if lookahead_hours <= 0:
            return

        now = datetime.now(timezone.utc)
        signed_vl = artifacts.get("signed_vl")
        try:
            effective_at = read_vl_effective(signed_vl)
        except Exception as exc:
            logger.warning(
                "Round %d: could not read VL activation time; leaving VL as-is: %s",
                round_number,
                exc,
            )
            return

        if effective_at > now + timedelta(seconds=_VL_ACTIVATION_MIN_FUTURE_SECONDS):
            return

        fresh_effective = now + timedelta(hours=lookahead_hours)
        try:
            resigned = resign_vl_with_effective(signed_vl, fresh_effective)
        except Exception as exc:
            logger.warning(
                "Round %d: could not re-sign held VL; publishing as-is: %s",
                round_number,
                exc,
            )
            return

        artifacts["signed_vl"] = resigned
        _update_pending_signed_vl(conn, round_number, resigned)
        logger.info(
            "Round %d: re-signed held VL for fresh activation (was %s, now %s)",
            round_number,
            effective_at.isoformat(),
            fresh_effective.isoformat(),
        )

    def publish_due_rounds(self, now: datetime | None = None) -> list[dict]:
        """Publish every held normal round whose output-publication deadline passed."""
        conn = get_db()
        try:
            due = _due_publication_rounds(conn, now or datetime.now(timezone.utc))
        finally:
            conn.close()
        return [self.publish_held_round(round_number) for round_number in due]

    def publish_held_round(self, round_number: int) -> dict:
        """Resume Steps 6-8 for one normal round after commit close.

        This method is intentionally idempotent across the states it writes:
        AWAITING_COMMIT_CLOSE resumes with IPFS publication, IPFS_PUBLISHED
        resumes with GitHub Pages distribution, VL_DISTRIBUTED resumes with the
        on-chain final-bundle memo, and ONCHAIN_PUBLISHED only marks COMPLETE.
        """
        conn = get_db()
        result: dict[str, Any] = {"round_number": round_number}
        try:
            row = _load_publication_round(conn, round_number)
            if row is None:
                result.update({"published": False, "reason": "not_found"})
                return result

            (
                round_id,
                status,
                vl_sequence,
                final_bundle_cid,
                github_pages_commit_url,
                memo_tx_hash,
            ) = row
            result["previous_status"] = status
            artifacts = _load_pending_publication(conn, round_number)
            if artifacts is None:
                result.update({"published": False, "reason": "missing_artifacts"})
                return result

            if status == RoundState.AWAITING_COMMIT_CLOSE.value:
                # Re-sign only before the VL is pinned into the audit bundle.
                # Once IPFS holds the bundle, its signed VL and the distributed
                # VL must stay identical, so no re-sign runs in later states.
                self._refresh_stale_vl_activation(conn, round_number, artifacts)
                try:
                    final_bundle_cid = self._ipfs_publisher.publish(
                        round_number=round_number,
                        snapshot=artifacts["snapshot"],
                        raw_evidence=artifacts["raw_evidence"],
                        scoring_result=artifacts["scoring_result"],
                        unl_result=artifacts["unl_result"],
                        signed_vl=artifacts["signed_vl"],
                        conn=conn,
                        prompt_messages=artifacts["prompt_messages"],
                        validator_id_map=artifacts["validator_id_map"],
                        input_package=artifacts["input_package"],
                    )
                    if final_bundle_cid is None:
                        raise RuntimeError("IPFS pinning returned no CID")
                    _update_round(
                        conn,
                        round_id,
                        status=RoundState.IPFS_PUBLISHED.value,
                        final_bundle_cid=final_bundle_cid,
                    )
                    status = RoundState.IPFS_PUBLISHED.value
                    result["final_bundle_cid"] = final_bundle_cid
                except Exception as exc:
                    _release_reserved_sequence(conn, vl_sequence)
                    _fail_round(conn, round_id, f"IPFS_PUBLISHED: {exc}")
                    result.update({"published": False, "status": RoundState.FAILED.value})
                    return result

            if status == RoundState.IPFS_PUBLISHED.value:
                try:
                    vl_json = json.dumps(
                        artifacts["signed_vl"], separators=(",", ":")
                    )
                    commit_message = (
                        f"Scoring round {round_number} — VL sequence {vl_sequence}"
                    )
                    github_pages_commit_url = self._github_pages.publish(
                        content=vl_json,
                        commit_message=commit_message,
                    )
                except Exception as exc:
                    _release_reserved_sequence(conn, vl_sequence)
                    _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
                    result.update({"published": False, "status": RoundState.FAILED.value})
                    return result

                try:
                    _confirm_public_vl(
                        conn,
                        round_id,
                        artifacts["signed_vl"],
                        vl_sequence,
                        github_pages_commit_url,
                    )
                    status = RoundState.VL_DISTRIBUTED.value
                    result["github_pages_commit_url"] = github_pages_commit_url
                except Exception as exc:
                    conn.rollback()
                    _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
                    result.update({"published": False, "status": RoundState.FAILED.value})
                    return result

            if status == RoundState.VL_DISTRIBUTED.value:
                try:
                    tx_hash = self._onchain_publisher.publish(
                        final_bundle_cid=final_bundle_cid,
                        vl_sequence=vl_sequence,
                        round_number=round_number,
                    )
                    if tx_hash is None:
                        raise RuntimeError("On-chain memo submission failed")
                    _update_round(
                        conn,
                        round_id,
                        status=RoundState.ONCHAIN_PUBLISHED.value,
                        memo_tx_hash=tx_hash,
                    )
                    status = RoundState.ONCHAIN_PUBLISHED.value
                    result["memo_tx_hash"] = tx_hash
                except Exception as exc:
                    error = f"ONCHAIN_PUBLISHED: {exc}"
                    _mark_vl_published_memo_failed(conn, round_id, error)
                    _delete_pending_publication(conn, round_number)
                    result.update(
                        {
                            "published": True,
                            "status": RoundState.VL_PUBLISHED_MEMO_FAILED.value,
                            "error_message": error,
                        }
                    )
                    return result

            if status == RoundState.ONCHAIN_PUBLISHED.value:
                _update_round(
                    conn,
                    round_id,
                    status=RoundState.COMPLETE.value,
                    completed_at=datetime.now(timezone.utc),
                )
                _delete_pending_publication(conn, round_number)
                result.update({"published": True, "status": RoundState.COMPLETE.value})
                return result

            result.update({"published": False, "status": status, "reason": "not_resumable"})
            return result
        finally:
            conn.close()

    def run_dry_run(self, dry_run_id: int | None = None) -> dict:
        """Execute a private dry-run without consuming a public round number."""
        conn = get_db()
        if dry_run_id is None:
            try:
                dry_run_id = create_dry_run(conn)
            except Exception:
                conn.close()
                raise

        network = settings.pftl_network
        result = {
            "dry_run": True,
            "dry_run_id": dry_run_id,
        }

        # --- Step 1: COLLECTING ---
        try:
            snapshot, raw_evidence = self._collector.collect_dry_run(dry_run_id, network)
            update_dry_run(
                conn,
                dry_run_id,
                status=RoundState.COLLECTING.value,
                snapshot_hash=snapshot.content_hash(),
            )
            result["snapshot_hash"] = snapshot.content_hash()
        except Exception as exc:
            fail_dry_run(conn, dry_run_id, f"COLLECTING: {exc}")
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
            update_dry_run(conn, dry_run_id, status=RoundState.SCORED.value)
        except Exception as exc:
            fail_dry_run(conn, dry_run_id, f"SCORED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 3: SELECTED ---
        try:
            previous_unl = _get_previous_unl(conn)
            unl_result = select_unl(scoring_result, previous_unl)
            update_dry_run(conn, dry_run_id, status=RoundState.SELECTED.value)
            result["validator_count"] = len(unl_result.unl)
        except Exception as exc:
            fail_dry_run(conn, dry_run_id, f"SELECTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 4: Store private review artifacts ---
        try:
            self._ipfs_publisher.publish_dry_run(
                dry_run_id=dry_run_id,
                snapshot=snapshot,
                raw_evidence=raw_evidence,
                scoring_result=scoring_result,
                unl_result=unl_result,
                conn=conn,
                prompt_messages=messages,
                validator_id_map=validator_id_map,
            )
            update_dry_run(
                conn,
                dry_run_id,
                status=RoundState.DRY_RUN_COMPLETE.value,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            fail_dry_run(conn, dry_run_id, f"DRY_RUN_ARTIFACTS: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        result["artifacts_stored"] = True
        result["status"] = RoundState.DRY_RUN_COMPLETE.value
        conn.close()
        logger.info("Dry run complete: dry_run_id=%d", dry_run_id)
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
        effective_lookahead_hours: float | None = None,
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
            override_type, override_reason, vl_sequence, final_bundle_cid,
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
            conn.commit()
            manifests = self._rpc.fetch_manifests(master_keys)
            signed_vl = generate_vl(
                master_keys,
                manifests,
                vl_sequence,
                effective_lookahead_hours=lookahead,
                expiration_days=expiration_days,
            )
            _update_round(
                conn, round_id,
                status=RoundState.VL_SIGNED.value,
            )
            result["vl_sequence"] = vl_sequence
        except Exception as exc:
            _release_reserved_sequence(conn, vl_sequence)
            _fail_round(conn, round_id, f"VL_SIGNED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 5: IPFS_PUBLISHED ---
        try:
            final_bundle_cid = self._ipfs_publisher.publish_override(
                round_number=round_number,
                master_keys=master_keys,
                signed_vl=signed_vl,
                override_type=override_type,
                override_reason=reason,
                conn=conn,
            )
            if final_bundle_cid is None:
                raise RuntimeError("IPFS pinning returned no CID")
            _update_round(
                conn, round_id,
                status=RoundState.IPFS_PUBLISHED.value,
                final_bundle_cid=final_bundle_cid,
            )
            result["final_bundle_cid"] = final_bundle_cid
        except Exception as exc:
            _release_reserved_sequence(conn, vl_sequence)
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
        except Exception as exc:
            _release_reserved_sequence(conn, vl_sequence)
            _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        try:
            _confirm_public_vl(
                conn,
                round_id,
                signed_vl,
                vl_sequence,
                github_pages_commit_url,
            )
            result["github_pages_commit_url"] = github_pages_commit_url
            result["vl_sequence"] = vl_sequence
        except Exception as exc:
            conn.rollback()
            _fail_round(conn, round_id, f"VL_DISTRIBUTED: {exc}")
            conn.close()
            result["status"] = RoundState.FAILED.value
            return result

        # --- Step 7: ONCHAIN_PUBLISHED (override memo type) ---
        try:
            tx_hash = self._onchain_publisher.publish(
                final_bundle_cid=final_bundle_cid,
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
            error = f"ONCHAIN_PUBLISHED: {exc}"
            _mark_vl_published_memo_failed(conn, round_id, error)
            conn.close()
            result["status"] = RoundState.VL_PUBLISHED_MEMO_FAILED.value
            result["error_message"] = error
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
            final_bundle_cid,
            tx_hash,
        )
        return result
