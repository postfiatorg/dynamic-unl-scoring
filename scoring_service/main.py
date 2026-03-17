"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from scoring_service.api import api_router
from scoring_service.config import settings
from scoring_service.database import init_db_if_needed
from scoring_service.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    configure_logging(debug=settings.debug, log_level=settings.log_level)
    init_db_if_needed()

    if settings.modal_endpoint_url:
        print(f"[startup] Modal endpoint configured: {settings.modal_endpoint_url}")
    else:
        print("[startup] No MODAL_ENDPOINT_URL — scoring will not work")

    if settings.pftl_enabled:
        print(f"[startup] PFTL configured (network: {settings.pftl_network})")
    else:
        print("[startup] PFTL not configured — on-chain publishing disabled")

    yield


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="Dynamic UNL Scoring Service",
        description="Automated validator scoring and UNL generation for the PFT Ledger",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


app = create_app()
