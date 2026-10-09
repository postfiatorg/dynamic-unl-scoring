"""Pydantic schemas for HTTP API request bodies.

These are transport-layer contracts — they describe the JSON shape
FastAPI expects at each endpoint. Distinct from the domain models in
``scoring_service/models/``, which represent long-lived concepts that
flow through the scoring pipeline (validator profiles, scoring
snapshots, agreement scores, etc.).
"""

from pydantic import BaseModel, Field, field_validator
from xrpl.core import addresscodec


class PublishCustomUNLRequest(BaseModel):
    """Request body for ``POST /api/scoring/admin/publish-unl/custom``."""

    master_keys: list[str] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    effective_lookahead_hours: float | None = Field(default=None, ge=0)
    expiration_days: int | None = Field(default=None, ge=1)

    @field_validator("master_keys")
    @classmethod
    def validate_master_keys(cls, master_keys: list[str]) -> list[str]:
        """Reject entries that cannot form a valid, unambiguous validator list."""
        seen: set[str] = set()
        for master_key in master_keys:
            try:
                addresscodec.decode_node_public_key(master_key)
            except ValueError as exc:
                raise ValueError(
                    f"invalid validator master key: {master_key!r}"
                ) from exc
            if master_key in seen:
                raise ValueError(
                    f"duplicate validator master key: {master_key!r}"
                )
            seen.add(master_key)
        return master_keys


class PublishFromRoundRequest(BaseModel):
    """Request body for ``POST /api/scoring/admin/publish-unl/from-round/{round_id}``."""

    reason: str = Field(..., min_length=1)
    effective_lookahead_hours: float | None = Field(default=None, ge=0)
    expiration_days: int | None = Field(default=None, ge=1)
