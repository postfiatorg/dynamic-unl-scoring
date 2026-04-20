"""Admin override endpoints — custom UNL publish and historical-round rollback.

These endpoints bypass the scoring pipeline (COLLECT/SCORE/SELECT) and
publish a foundation-specified UNL through the back half of the state
machine (VL_SIGNED → IPFS_PUBLISHED → VL_DISTRIBUTED → ONCHAIN_PUBLISHED)
using a distinct on-chain memo type. Temporary scaffolding; removed at
the Phase 3 authority-transfer boundary.
"""

import logging
import threading

from fastapi import APIRouter, Header, status
from fastapi.responses import JSONResponse

from scoring_service.api._helpers import check_admin_auth, check_lock_available
from scoring_service.api.schemas import (
    PublishCustomUNLRequest,
    PublishFromRoundRequest,
)
from scoring_service.constants import OVERRIDE_TYPE_CUSTOM, OVERRIDE_TYPE_ROLLBACK
from scoring_service.database import get_db
from scoring_service.services.ipfs_publisher import get_audit_trail_file
from scoring_service.services.orchestrator import ScoringOrchestrator
from scoring_service.services.scheduler import _release_lock, _try_acquire_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scoring")


def _run_override_in_background(
    master_keys: list[str],
    reason: str,
    override_type: str,
    effective_lookahead_hours: float | None,
    expiration_days: int | None,
) -> None:
    """Background worker for override publishes. Owns the advisory lock lifecycle."""
    conn = get_db()
    try:
        if not _try_acquire_lock(conn):
            logger.warning("Background override: advisory lock already held, aborting")
            conn.close()
            return

        conn.close()

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
            release_conn = get_db()
            _release_lock(release_conn)
            release_conn.close()
        except Exception:
            pass


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

    lock_error = check_lock_available()
    if lock_error is not None:
        return lock_error

    thread = threading.Thread(
        target=_run_override_in_background,
        args=(
            payload.master_keys,
            payload.reason,
            OVERRIDE_TYPE_CUSTOM,
            payload.effective_lookahead_hours,
            payload.expiration_days,
        ),
        daemon=True,
    )
    thread.start()

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

    Looks up the ``unl.json`` audit-trail file stored for the referenced round,
    extracts its master-key list, and publishes it via the standard override
    pipeline. Use for clean rollback to a known-good state.
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
        unl_data = get_audit_trail_file(conn, round_number, "unl.json")
    finally:
        conn.close()

    if unl_data is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": f"No unl.json audit-trail file stored for round {round_id}"
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

    lock_error = check_lock_available()
    if lock_error is not None:
        return lock_error

    thread = threading.Thread(
        target=_run_override_in_background,
        args=(
            master_keys,
            payload.reason,
            OVERRIDE_TYPE_ROLLBACK,
            payload.effective_lookahead_hours,
            payload.expiration_days,
        ),
        daemon=True,
    )
    thread.start()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "override_type": OVERRIDE_TYPE_ROLLBACK,
            "source_round_id": round_id,
            "source_round_number": round_number,
            "status": "started",
        },
    )
