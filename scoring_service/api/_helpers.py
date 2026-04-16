"""Shared precondition helpers for admin-gated API endpoints.

Each helper returns a prebuilt ``JSONResponse`` when the precondition
fails (so the caller can ``return`` it directly) and ``None`` on success.
This keeps the admin-gated write paths free of duplicated inline auth
and lock-check code.
"""

from fastapi import status
from fastapi.responses import JSONResponse

from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.services.scheduler import _release_lock, _try_acquire_lock


def check_admin_auth(x_api_key: str | None) -> JSONResponse | None:
    """Return a 403 response if admin auth fails, otherwise ``None``."""
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
    return None


def check_lock_available() -> JSONResponse | None:
    """Return a 409 response if a round is already in progress, otherwise ``None``."""
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
    return None
