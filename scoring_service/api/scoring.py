"""Scoring endpoints — manual trigger, round status, current UNL, config, health."""

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import JSONResponse

from scoring_service.api._helpers import (
    acquire_round_lock,
    check_admin_auth,
    release_round_lock,
)
from scoring_service.clients.pftl import DROPS_PER_PFT, PFTLClient
from scoring_service.config import settings
from scoring_service.constants import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)
from scoring_service.database import get_db
from scoring_service.services.dry_runs import create_dry_run, fail_dry_run
from scoring_service.services.ipfs_publisher import get_selected_unl_file
from scoring_service.services.orchestrator import (
    OPERATIONALLY_PUBLISHED_STATES,
    RoundState,
    ScoringOrchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scoring")

WALLET_CACHE_TTL_SECONDS = 30
WALLET_MIN_BALANCE_DROPS = 10 * DROPS_PER_PFT

_wallet_cache: dict = {"timestamp": 0.0, "result": None}


def _utcnow() -> datetime:
    """Wrapped so tests can patch the clock deterministically."""
    return datetime.now(tz=timezone.utc)


def _monotonic_seconds() -> float:
    """Wrapped so tests can patch the cache clock deterministically."""
    return time.time()


def clear_wallet_cache() -> None:
    """Reset the module-level wallet-health cache. Exposed for tests."""
    _wallet_cache["timestamp"] = 0.0
    _wallet_cache["result"] = None


def _format_elapsed(seconds: float) -> str:
    if seconds < SECONDS_PER_MINUTE:
        return f"{int(seconds)} seconds"
    if seconds < SECONDS_PER_HOUR:
        return f"{int(seconds / SECONDS_PER_MINUTE)} minutes"
    if seconds < SECONDS_PER_DAY:
        hours = seconds / SECONDS_PER_HOUR
        if hours < 10:
            return f"{hours:.1f} hours"
        return f"{int(hours)} hours"
    return f"{int(seconds / SECONDS_PER_DAY)} days"


def _run_round_in_background(
    dry_run: bool,
    lock_conn,
    dry_run_id: int | None = None,
) -> None:
    """Background worker that owns the advisory lock lifecycle."""
    try:
        orchestrator = ScoringOrchestrator()
        if dry_run:
            result = orchestrator.run_dry_run(dry_run_id=dry_run_id)
        else:
            result = orchestrator.run_round()
        logger.info(
            "Background round finished: status=%s, round=%s, dry_run_id=%s",
            result.get("status"),
            result.get("round_number"),
            result.get("dry_run_id"),
        )
    except Exception as exc:
        if dry_run and dry_run_id is not None:
            try:
                fail_dry_run(lock_conn, dry_run_id, f"UNEXPECTED: {exc}")
            except Exception:
                logger.exception("Failed to mark dry-run %d as failed", dry_run_id)
        logger.exception("Background round failed with unexpected error")
    finally:
        try:
            release_round_lock(lock_conn)
        except Exception:
            logger.exception("Failed to release round advisory lock")


@router.post("/trigger")
def trigger_round(
    dry_run: bool = Query(default=False),
    x_api_key: str | None = Header(default=None),
):
    """Trigger a scoring round manually.

    Returns 202 with the round info if started, 409 if a round is
    already in progress, 403 if auth fails or endpoint is not configured.
    """
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    lock_conn, lock_error = acquire_round_lock()
    if lock_error is not None:
        return lock_error

    dry_run_id = None
    try:
        dry_run_id = create_dry_run(lock_conn) if dry_run else None
        thread = threading.Thread(
            target=_run_round_in_background,
            args=(dry_run, lock_conn, dry_run_id),
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        if dry_run_id is not None:
            try:
                fail_dry_run(lock_conn, dry_run_id, f"THREAD_START: {exc}")
            except Exception:
                logger.exception("Failed to mark dry-run %d as failed", dry_run_id)
        release_round_lock(lock_conn)
        raise

    content = {
        "dry_run": dry_run,
        "status": "started",
    }
    if dry_run_id is not None:
        content["dry_run_id"] = dry_run_id

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=content,
    )


@router.get("/rounds")
def list_rounds(
    limit: int = Query(default=settings.default_page_limit, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List recent scoring rounds, newest first."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, round_number, status, snapshot_hash, scores_hash,
                   vl_sequence, final_bundle_cid, input_package_cid,
                   input_package_hash, input_frozen_at,
                   github_pages_commit_url, memo_tx_hash,
                   override_type, override_reason, error_message,
                   started_at, completed_at, created_at
            FROM scoring_rounds
            WHERE status != %s
            ORDER BY round_number DESC
            LIMIT %s OFFSET %s
            """,
            (RoundState.DRY_RUN_COMPLETE.value, limit, offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*) FROM scoring_rounds WHERE status != %s",
            (RoundState.DRY_RUN_COMPLETE.value,),
        )
        count_row = cursor.fetchone()
        total = count_row[0] if count_row else 0
        cursor.close()
    finally:
        connection.close()

    rounds = [
        {
            "id": r[0],
            "round_number": r[1],
            "status": r[2],
            "snapshot_hash": r[3],
            "scores_hash": r[4],
            "vl_sequence": r[5],
            "final_bundle_cid": r[6],
            "input_package_cid": r[7],
            "input_package_hash": r[8],
            "input_frozen_at": r[9].isoformat() if r[9] else None,
            "github_pages_commit_url": r[10],
            "memo_tx_hash": r[11],
            "override_type": r[12],
            "override_reason": r[13],
            "error_message": r[14],
            "started_at": r[15].isoformat() if r[15] else None,
            "completed_at": r[16].isoformat() if r[16] else None,
            "created_at": r[17].isoformat() if r[17] else None,
        }
        for r in rows
    ]

    return JSONResponse(content={
        "rounds": rounds,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.get("/rounds/{round_id}")
def get_round(round_id: int):
    """Get detailed info for a specific scoring round."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT id, round_number, status, snapshot_hash, scores_hash,
                   vl_sequence, final_bundle_cid, input_package_cid,
                   input_package_hash, input_frozen_at,
                   github_pages_commit_url, memo_tx_hash,
                   override_type, override_reason, error_message,
                   started_at, completed_at, created_at
            FROM scoring_rounds
            WHERE id = %s
            AND status != %s
            """,
            (round_id, RoundState.DRY_RUN_COMPLETE.value),
        )
        row = cursor.fetchone()
        cursor.close()
    finally:
        connection.close()

    if row is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"Round {round_id} not found"},
        )

    return JSONResponse(content={
        "id": row[0],
        "round_number": row[1],
        "status": row[2],
        "snapshot_hash": row[3],
        "scores_hash": row[4],
        "vl_sequence": row[5],
        "final_bundle_cid": row[6],
        "input_package_cid": row[7],
        "input_package_hash": row[8],
        "input_frozen_at": row[9].isoformat() if row[9] else None,
        "github_pages_commit_url": row[10],
        "memo_tx_hash": row[11],
        "override_type": row[12],
        "override_reason": row[13],
        "error_message": row[14],
        "started_at": row[15].isoformat() if row[15] else None,
        "completed_at": row[16].isoformat() if row[16] else None,
        "created_at": row[17].isoformat() if row[17] else None,
    })


@router.get("/unl/current")
def get_current_unl():
    """Get the current active UNL from the last operationally published round."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT round_number, status FROM scoring_rounds
            WHERE status IN %s
            ORDER BY round_number DESC
            LIMIT 1
            """,
            (tuple(s.value for s in OPERATIONALLY_PUBLISHED_STATES),),
        )
        row = cursor.fetchone()
        cursor.close()

        if row is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "No published scoring rounds yet"},
            )

        round_number, round_status = row
        unl_data = get_selected_unl_file(connection, round_number)
    finally:
        connection.close()

    if unl_data is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "UNL data not found for latest completed round"},
        )

    return JSONResponse(content={
        "round_number": round_number,
        "status": round_status,
        "unl": unl_data.get("unl", []),
        "alternates": unl_data.get("alternates", []),
        "memo_warning": round_status == RoundState.VL_PUBLISHED_MEMO_FAILED.value,
    })


def _check_scheduler(connection) -> dict:
    """Healthy when the newest round row was created within 2 × cadence.

    The scheduler creates a new `scoring_rounds` row every cadence period;
    the row-creation timestamp is the heartbeat. No dedicated heartbeat
    column is introduced — the existing cadence IS the signal.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT MAX(created_at)
            FROM scoring_rounds
            WHERE status != %s
            AND override_type IS NULL
            """,
            (RoundState.DRY_RUN_COMPLETE.value,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()

    last_created = row[0] if row else None
    if last_created is None:
        return {"healthy": False, "detail": "no rounds created yet"}

    cadence_hours = settings.scoring_cadence_hours
    threshold_seconds = 2 * cadence_hours * SECONDS_PER_HOUR
    elapsed_seconds = (_utcnow() - last_created).total_seconds()
    elapsed_text = _format_elapsed(max(0.0, elapsed_seconds))
    healthy = elapsed_seconds <= threshold_seconds
    return {"healthy": healthy, "detail": f"last tick {elapsed_text} ago"}


def _check_llm_endpoint(connection) -> dict:
    """Unhealthy when the most recent round failed AT the scoring stage.

    Heuristic: a round that collected and froze inputs (`snapshot_hash` and
    `input_package_cid` set) but never produced scores (`scores_hash` null)
    and ended in status FAILED failed at the scoring stage. Earlier input
    package failures and later-stage failures are not LLM endpoint failures.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT status, snapshot_hash, scores_hash, input_package_cid
            FROM scoring_rounds
            WHERE status != %s
            ORDER BY round_number DESC
            LIMIT 1
            """,
            (RoundState.DRY_RUN_COMPLETE.value,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()

    if row is None:
        return {"healthy": True, "detail": "no rounds yet"}

    last_status, snapshot_hash, scores_hash, input_package_cid = row
    if (
        last_status == "FAILED"
        and snapshot_hash
        and input_package_cid
        and not scores_hash
    ):
        return {"healthy": False, "detail": "last round failed at scoring stage"}
    return {"healthy": True, "detail": "last round scored cleanly"}


def _check_publisher_wallet() -> dict:
    """Live RPC check against the publisher wallet, cached ~30 seconds.

    Healthy when account_info returns with balance above the minimum
    sufficient for several memo transactions. The cache prevents banner
    polling from hammering the RPC node when the Scoring page auto-
    refreshes every few seconds.
    """
    now = _monotonic_seconds()
    cached_result = _wallet_cache["result"]
    if (
        cached_result is not None
        and now - _wallet_cache["timestamp"] < WALLET_CACHE_TTL_SECONDS
    ):
        return cached_result

    try:
        client = PFTLClient()
        balance_drops = client.get_balance_drops()
        balance_pft = balance_drops // DROPS_PER_PFT
        if balance_drops < WALLET_MIN_BALANCE_DROPS:
            result = {
                "healthy": False,
                "detail": f"balance {balance_pft} PFT below minimum",
            }
        else:
            result = {
                "healthy": True,
                "detail": f"balance {balance_pft} PFT",
            }
    except Exception as exc:  # noqa: BLE001 — any failure here is "unhealthy"
        result = {
            "healthy": False,
            "detail": f"RPC unreachable: {exc}",
        }

    _wallet_cache["timestamp"] = now
    _wallet_cache["result"] = result
    return result


@router.get("/health")
def get_pipeline_health():
    """Public pipeline-status health for the Scoring page banner.

    Returns three signals — scheduler, llm_endpoint, publisher_wallet —
    each with a boolean `healthy` field and a short human-readable
    `detail` string. Distinct from the bare `/health` endpoint, which is
    a database-ping liveness probe for infrastructure health checks.
    """
    connection = get_db()
    try:
        scheduler = _check_scheduler(connection)
        llm_endpoint = _check_llm_endpoint(connection)
    finally:
        connection.close()

    publisher_wallet = _check_publisher_wallet()

    return JSONResponse(
        content={
            "scheduler": scheduler,
            "llm_endpoint": llm_endpoint,
            "publisher_wallet": publisher_wallet,
        }
    )


@router.get("/config")
def get_config():
    """Public read-only runtime configuration for the scoring pipeline.

    Exposes the values the explorer needs to render live countdowns,
    churn-gap chips, and methodology text without hardcoding constants.
    """
    return JSONResponse(content={
        "cadence_hours": float(settings.scoring_cadence_hours),
        "unl_score_cutoff": settings.unl_score_cutoff,
        "unl_max_size": settings.unl_max_size,
        "unl_min_score_gap": settings.unl_min_score_gap,
    })
