"""Admin endpoints — dry-run review, custom UNL publish, and rollback.

Override endpoints bypass the scoring pipeline (COLLECT/SCORE/SELECT) and
publish a foundation-specified UNL through the back half of the state
machine (VL_SIGNED → IPFS_PUBLISHED → VL_DISTRIBUTED → ONCHAIN_PUBLISHED)
using a distinct on-chain memo type. Temporary scaffolding; removed at
the Phase 3 authority-transfer boundary.
"""

import logging
import threading

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import JSONResponse

from scoring_service.api._helpers import (
    acquire_round_lock,
    check_admin_auth,
    release_round_lock,
)
from scoring_service.api.schemas import (
    PublishCustomUNLRequest,
    PublishFromRoundRequest,
)
from scoring_service.constants import OVERRIDE_TYPE_CUSTOM, OVERRIDE_TYPE_ROLLBACK
from scoring_service.database import get_db
from scoring_service.services.dry_runs import (
    get_dry_run,
    get_dry_run_artifact,
    list_dry_runs,
)
from scoring_service.services.ipfs_publisher import get_selected_unl_file
from scoring_service.services.orchestrator import ScoringOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scoring")


@router.get("/admin/dry-runs")
def list_admin_dry_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_api_key: str | None = Header(default=None),
):
    """List private dry-runs for admin review."""
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    conn = get_db()
    try:
        dry_runs, total = list_dry_runs(conn, limit, offset)
    finally:
        conn.close()

    return JSONResponse(content={
        "dry_runs": dry_runs,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.get("/admin/dry-runs/{dry_run_id}")
def get_admin_dry_run(
    dry_run_id: int,
    x_api_key: str | None = Header(default=None),
):
    """Get one private dry-run status record for admin review."""
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    conn = get_db()
    try:
        dry_run = get_dry_run(conn, dry_run_id)
    finally:
        conn.close()

    if dry_run is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"Dry-run {dry_run_id} not found"},
        )

    return JSONResponse(content=dry_run)


@router.get("/admin/dry-runs/{dry_run_id}/{file_path:path}")
def get_admin_dry_run_artifact(
    dry_run_id: int,
    file_path: str,
    x_api_key: str | None = Header(default=None),
):
    """Get one private dry-run artifact for admin review."""
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    conn = get_db()
    try:
        content = get_dry_run_artifact(conn, dry_run_id, file_path)
    finally:
        conn.close()

    if content is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": f"File not found: dry_run {dry_run_id}, path {file_path}"
            },
        )

    return JSONResponse(content=content, media_type="application/json")


def _run_override_in_background(
    master_keys: list[str],
    reason: str,
    override_type: str,
    effective_lookahead_hours: float | None,
    expiration_days: int | None,
    lock_conn,
) -> None:
    """Background worker for override publishes. Owns the advisory lock lifecycle."""
    try:
        orchestrator = ScoringOrchestrator()
        result = orchestrator.run_override_round(
            master_keys=master_keys,
            reason=reason,
            override_type=override_type,
            effective_lookahead_hours=effective_lookahead_hours,
            expiration_days=expiration_days,
        )
        logger.info(
            "Background override round finished: type=%s, status=%s, round=%s",
            override_type,
            result.get("status"),
            result.get("round_number"),
        )
    except Exception:
        logger.exception("Background override round failed with unexpected error")
    finally:
        try:
            release_round_lock(lock_conn)
        except Exception:
            logger.exception("Failed to release round advisory lock")


@router.post("/admin/publish-unl/custom")
def publish_custom_unl(
    payload: PublishCustomUNLRequest,
    x_api_key: str | None = Header(default=None),
):
    """Publish a signed VL containing an operator-specified set of master keys.

    Skips scoring. Use for emergency republishes, seeding a new environment,
    or any case where the operator knows exactly which validators should be
    trusted and needs a signed VL published through the standard pipeline.
    """
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    lock_conn, lock_error = acquire_round_lock()
    if lock_error is not None:
        return lock_error

    try:
        thread = threading.Thread(
            target=_run_override_in_background,
            args=(
                payload.master_keys,
                payload.reason,
                OVERRIDE_TYPE_CUSTOM,
                payload.effective_lookahead_hours,
                payload.expiration_days,
                lock_conn,
            ),
            daemon=True,
        )
        thread.start()
    except Exception:
        release_round_lock(lock_conn)
        raise

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "override_type": OVERRIDE_TYPE_CUSTOM,
            "status": "started",
        },
    )


@router.post("/admin/publish-unl/from-round/{round_id}")
def publish_from_round(
    round_id: int,
    payload: PublishFromRoundRequest,
    x_api_key: str | None = Header(default=None),
):
    """Republish the UNL from a historical round under a fresh VL sequence.

    Looks up the selected-UNL artifact stored for the referenced round, extracts
    its master-key list, and publishes it via the standard override pipeline.
    Use for clean rollback to a known-good state.
    """
    auth_error = check_admin_auth(x_api_key)
    if auth_error is not None:
        return auth_error

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT round_number FROM scoring_rounds WHERE id = %s",
            (round_id,),
        )
        row = cursor.fetchone()
        cursor.close()

        if row is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"Round {round_id} not found"},
            )

        round_number = row[0]
        unl_data = get_selected_unl_file(conn, round_number)
    finally:
        conn.close()

    if unl_data is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": f"No selected UNL artifact stored for round {round_id}"
            },
        )

    master_keys = unl_data.get("unl") or []
    if not master_keys:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": f"Round {round_id} audit trail contains no UNL master keys"
            },
        )

    lock_conn, lock_error = acquire_round_lock()
    if lock_error is not None:
        return lock_error

    try:
        thread = threading.Thread(
            target=_run_override_in_background,
            args=(
                master_keys,
                payload.reason,
                OVERRIDE_TYPE_ROLLBACK,
                payload.effective_lookahead_hours,
                payload.expiration_days,
                lock_conn,
            ),
            daemon=True,
        )
        thread.start()
    except Exception:
        release_round_lock(lock_conn)
        raise

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "override_type": OVERRIDE_TYPE_ROLLBACK,
            "source_round_id": round_id,
            "source_round_number": round_number,
            "status": "started",
        },
    )
