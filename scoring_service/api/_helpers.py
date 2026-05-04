"""Shared precondition helpers for admin-gated API endpoints."""

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


def acquire_round_lock() -> tuple[object | None, JSONResponse | None]:
    """Acquire the shared round lock and return its owning DB connection.

    The returned connection must remain open for the full state-changing
    execution window because PostgreSQL advisory locks are session-scoped.
    Callers that receive a connection are responsible for releasing the lock
    and closing the connection.
    """
    conn = get_db()
    try:
        conn.autocommit = True
        if _try_acquire_lock(conn):
            return conn, None
    except Exception:
        conn.close()
        raise

    conn.close()
    return None, JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "A scoring round is already in progress"},
    )


def release_round_lock(conn) -> None:
    """Release a previously acquired round lock and close its connection."""
    try:
        _release_lock(conn)
    finally:
        conn.close()
