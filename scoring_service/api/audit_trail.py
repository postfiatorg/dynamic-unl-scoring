"""HTTPS fallback endpoint for audit trail files."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from scoring_service.database import get_db
from scoring_service.services.ipfs_publisher import get_audit_trail_file
from scoring_service.services.orchestrator import RoundState

router = APIRouter(prefix="/api/scoring")


@router.get("/rounds/{round_number}/{file_path:path}")
def serve_audit_trail_file(round_number: int, file_path: str):
    """Serve a single audit trail file for a scoring round."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM scoring_rounds
            WHERE round_number = %s
            AND status != %s
            """,
            (round_number, RoundState.DRY_RUN_COMPLETE.value),
        )
        public_round = cursor.fetchone()
        cursor.close()
        content = (
            get_audit_trail_file(connection, round_number, file_path)
            if public_round
            else None
        )
    finally:
        connection.close()

    if content is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"File not found: round {round_number}, path {file_path}"},
        )

    return JSONResponse(content=content, media_type="application/json")
