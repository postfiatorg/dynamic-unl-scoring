"""Scoring endpoints — manual trigger, round status, and current UNL."""

import logging
import threading

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import JSONResponse

from scoring_service.api._helpers import check_admin_auth, check_lock_available
from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.services.ipfs_publisher import get_audit_trail_file
from scoring_service.services.orchestrator import RoundState, ScoringOrchestrator
from scoring_service.services.scheduler import _release_lock, _try_acquire_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scoring")


def _run_round_in_background(dry_run: bool) -> None:
    """Background worker that owns the advisory lock lifecycle."""
    conn = get_db()
    try:
        if not _try_acquire_lock(conn):
            logger.warning("Background trigger: advisory lock already held, aborting")
            conn.close()
            return

        conn.close()

        orchestrator = ScoringOrchestrator()
        result = orchestrator.run_round(dry_run=dry_run)
        logger.info(
            "Background round finished: status=%s, round=%s",
            result.get("status"),
            result.get("round_number"),
        )
    except Exception:
        logger.exception("Background round failed with unexpected error")
    finally:
        try:
            release_conn = get_db()
            _release_lock(release_conn)
            release_conn.close()
        except Exception:
            pass


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

    lock_error = check_lock_available()
    if lock_error is not None:
        return lock_error

    thread = threading.Thread(
        target=_run_round_in_background,
        args=(dry_run,),
        daemon=True,
    )
    thread.start()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "dry_run": dry_run,
            "status": "started",
        },
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
                   vl_sequence, ipfs_cid, github_pages_commit_url, memo_tx_hash,
                   override_type, override_reason, error_message,
                   started_at, completed_at, created_at
            FROM scoring_rounds
            ORDER BY round_number DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM scoring_rounds")
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
            "ipfs_cid": r[6],
            "github_pages_commit_url": r[7],
            "memo_tx_hash": r[8],
            "override_type": r[9],
            "override_reason": r[10],
            "error_message": r[11],
            "started_at": r[12].isoformat() if r[12] else None,
            "completed_at": r[13].isoformat() if r[13] else None,
            "created_at": r[14].isoformat() if r[14] else None,
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
                   vl_sequence, ipfs_cid, github_pages_commit_url, memo_tx_hash,
                   override_type, override_reason, error_message,
                   started_at, completed_at, created_at
            FROM scoring_rounds
            WHERE id = %s
            """,
            (round_id,),
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
        "ipfs_cid": row[6],
        "github_pages_commit_url": row[7],
        "memo_tx_hash": row[8],
        "override_type": row[9],
        "override_reason": row[10],
        "error_message": row[11],
        "started_at": row[12].isoformat() if row[12] else None,
        "completed_at": row[13].isoformat() if row[13] else None,
        "created_at": row[14].isoformat() if row[14] else None,
    })


@router.get("/unl/current")
def get_current_unl():
    """Get the current active UNL from the last successful round."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT round_number FROM scoring_rounds
            WHERE status = %s
            ORDER BY round_number DESC
            LIMIT 1
            """,
            (RoundState.COMPLETE.value,),
        )
        row = cursor.fetchone()
        cursor.close()

        if row is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "No completed scoring rounds yet"},
            )

        round_number = row[0]
        unl_data = get_audit_trail_file(connection, round_number, "unl.json")
    finally:
        connection.close()

    if unl_data is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "UNL data not found for latest completed round"},
        )

    return JSONResponse(content={
        "round_number": round_number,
        "unl": unl_data.get("unl", []),
        "alternates": unl_data.get("alternates", []),
    })


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
