"""Validator List serving endpoint."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from scoring_service.database import get_db
from scoring_service.services.vl_sequence import get_current_vl

router = APIRouter()


@router.get("/vl.json")
def serve_vl():
    """Serve the latest signed Validator List."""
    connection = get_db()
    try:
        vl = get_current_vl(connection)
    finally:
        connection.close()

    if vl is None:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "No validator list published yet"})

    return JSONResponse(content=vl, media_type="application/json")
