"""HTTPS fallback endpoint for audit trail files."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from scoring_service.database import get_db
from scoring_service.services.ipfs_publisher import get_audit_trail_file

router = APIRouter(prefix="/api/scoring")


@router.get("/rounds/{round_number}/{file_path:path}")
def serve_audit_trail_file(round_number: int, file_path: str):
    """Serve a single audit trail file for a scoring round."""
    connection = get_db()
    try:
        content = get_audit_trail_file(connection, round_number, file_path)
    finally:
        connection.close()

    if content is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"File not found: round {round_number}, path {file_path}"},
        )

    return JSONResponse(content=content, media_type="application/json")
