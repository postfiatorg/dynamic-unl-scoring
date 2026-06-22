"""Operator-visibility convergence endpoints (M2.6.5).

Read-only HTTP surface over the convergence state produced by the M2.6
ingestion, verification, comparison, and sealing pipeline. Each endpoint returns
one stable shape per round — a live participation tally before the report seals,
the immutable stored report after — keyed by on-chain round number, plus a
current-round alias. Strictly read-only with respect to canonical Validator List
publication; a sealed round is served from stored content, never recomputed, so
responses match the pinned `convergence_bundle_cid` and its on-chain anchor.

This router is registered ahead of the audit-trail router so
`/rounds/{round_number}/convergence` is matched before the audit-trail
`/rounds/{round_number}/{file_path:path}` catch-all would treat `convergence`
as a file name.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from scoring_service.api._helpers import public_round_exists
from scoring_service.database import get_db
from scoring_service.services.convergence_verification import (
    PHASE_NOT_TRACKED,
    latest_announced_round,
    round_convergence_view,
)

router = APIRouter(prefix="/api/scoring")

# A sealed report is immutable and content-addressed, so it is cacheable
# indefinitely; a live tally changes as commits and reveals land, so it carries
# only a short freshness window.
CONVERGENCE_LIVE_CACHE_SECONDS = 15
_SEALED_CACHE_CONTROL = "public, max-age=31536000, immutable"
_LIVE_CACHE_CONTROL = f"public, max-age={CONVERGENCE_LIVE_CACHE_SECONDS}"


def _cache_headers(view: dict) -> dict:
    control = _SEALED_CACHE_CONTROL if view["finalized"] else _LIVE_CACHE_CONTROL
    return {"Cache-Control": control}


@router.get("/rounds/{round_number}/convergence")
def get_round_convergence(round_number: int):
    """Convergence state for one round, keyed by on-chain round number.

    Serves the immutable sealed report once finalized, the live participation
    tally before that, and an explicit `not_tracked` phase for a real round with
    no convergence data (override, not-yet-announced, or pre-protocol). A round
    number that was never scored returns 404.
    """
    connection = get_db()
    try:
        view = round_convergence_view(connection, round_number)
        if view["phase"] == PHASE_NOT_TRACKED and not public_round_exists(
            connection, round_number
        ):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": f"Round {round_number} not found"},
            )
    finally:
        connection.close()
    return JSONResponse(content=view, headers=_cache_headers(view))


@router.get("/convergence/current")
def get_current_convergence():
    """Convergence state for the latest announced round.

    Resolves the most recent round announcement so callers need no round id. An
    announced round is always sealed or live; when nothing has been announced
    yet, returns an explicit `not_tracked` view with a null round number.
    """
    connection = get_db()
    try:
        round_number = latest_announced_round(connection)
        if round_number is None:
            view = {
                "round_number": None,
                "phase": PHASE_NOT_TRACKED,
                "finalized": False,
            }
        else:
            view = round_convergence_view(connection, round_number)
    finally:
        connection.close()
    return JSONResponse(content=view, headers=_cache_headers(view))
