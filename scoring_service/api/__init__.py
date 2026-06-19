from fastapi import APIRouter

from .admin import router as admin_router
from .audit_trail import router as audit_trail_router
from .convergence import router as convergence_router
from .health import router as health_router
from .scoring import router as scoring_router
from .vl import router as vl_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(vl_router, tags=["vl"])
# Before audit-trail so `/rounds/{n}/convergence` wins over its `{file_path:path}` catch-all.
api_router.include_router(convergence_router, tags=["convergence"])
api_router.include_router(audit_trail_router, tags=["audit-trail"])
api_router.include_router(scoring_router, tags=["scoring"])
api_router.include_router(admin_router, tags=["admin"])
