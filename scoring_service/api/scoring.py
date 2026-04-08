"""Admin scoring endpoints — manual trigger and round management."""

import logging
import threading

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import JSONResponse

from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.services.orchestrator import ScoringOrchestrator
from scoring_service.services.scheduler import (
    _release_lock,
    _try_acquire_lock,
)

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
    if not settings.admin_api_key:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "Admin endpoint not configured"},
        )

    if x_api_key != settings.admin_api_key:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "Invalid API key"},
        )

    conn = get_db()
    try:
        lock_available = _try_acquire_lock(conn)
        if lock_available:
            _release_lock(conn)
    finally:
        conn.close()

    if not lock_available:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "A scoring round is already in progress"},
        )

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
