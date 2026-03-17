"""Health check endpoint."""

from fastapi import APIRouter

from scoring_service.database import get_db

router = APIRouter()


@router.get("/health")
def health():
    """Verify the service and database are operational."""
    connection = get_db()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
    finally:
        connection.close()
    return {"status": "ok"}
