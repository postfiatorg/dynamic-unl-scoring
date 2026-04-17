"""Pydantic schemas for HTTP API request bodies.

These are transport-layer contracts — they describe the JSON shape
FastAPI expects at each endpoint. Distinct from the domain models in
``scoring_service/models/``, which represent long-lived concepts that
flow through the scoring pipeline (validator profiles, scoring
snapshots, agreement scores, etc.).
"""

from pydantic import BaseModel, Field


class PublishCustomUNLRequest(BaseModel):
    """Request body for ``POST /api/scoring/admin/publish-unl/custom``."""

    master_keys: list[str] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    effective_lookahead_hours: float | None = Field(default=None, ge=0)
    expiration_days: int | None = Field(default=None, ge=1)


class PublishFromRoundRequest(BaseModel):
    """Request body for ``POST /api/scoring/admin/publish-unl/from-round/{round_id}``."""

    reason: str = Field(..., min_length=1)
    effective_lookahead_hours: float | None = Field(default=None, ge=0)
    expiration_days: int | None = Field(default=None, ge=1)
