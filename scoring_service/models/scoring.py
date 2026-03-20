"""Data models for the scoring pipeline.

Each data collection client (VHS, ASN, MaxMind, Identity) produces instances
of these models. The snapshot assembler combines them into a ScoringSnapshot
that the LLM scorer consumes.
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AgreementScore(BaseModel):
    """Validator agreement score for a time window (1h, 24h, or 30d)."""

    score: Optional[float] = None
    total: Optional[int] = None
    missed: Optional[int] = None


class ASNInfo(BaseModel):
    """Autonomous System Number lookup result for an IP address."""

    asn: Optional[int] = None
    as_name: Optional[str] = None


class GeoLocation(BaseModel):
    """Geographic location from MaxMind GeoIP2 Precision Insights."""

    continent: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None


class IdentityAttestation(BaseModel):
    """On-chain identity verification status from pf_identity_v1 memos."""

    verified: Optional[bool] = None
    entity_type: Optional[str] = None
    domain_attested: Optional[bool] = None
    name: Optional[str] = None


class ValidatorProfile(BaseModel):
    """Complete validator profile combining data from multiple sources.

    Core fields (master_key through base_fee) come from VHS. The ip field
    comes from probing each topology node's /crawl endpoint on port 2559,
    which returns pubkey_validator in the server section — matching that
    against this validator's master_key establishes the IP mapping. Once the
    IP is known, asn and geolocation are derived via ASN lookups and MaxMind
    respectively. Identity comes from on-chain pf_identity_v1 memos.
    """

    master_key: str
    signing_key: str
    domain: Optional[str] = None
    domain_verified: Optional[bool] = None
    agreement_1h: AgreementScore = Field(default_factory=AgreementScore)
    agreement_24h: AgreementScore = Field(default_factory=AgreementScore)
    agreement_30d: AgreementScore = Field(default_factory=AgreementScore)
    server_version: str = ""
    unl: bool = False
    base_fee: Optional[int] = None
    ip: Optional[str] = None
    asn: Optional[ASNInfo] = None
    geolocation: Optional[GeoLocation] = None
    identity: Optional[IdentityAttestation] = None


class ScoringSnapshot(BaseModel):
    """Top-level scoring snapshot combining all data sources.

    Assembled by the DataCollectorService, consumed by the LLM scorer.
    The content_hash method provides integrity verification for the audit trail.
    """

    round_number: int
    network: str
    snapshot_timestamp: datetime
    snapshot_ledger_index: Optional[int] = None
    validators: list[ValidatorProfile]

    def content_hash(self) -> str:
        """Compute SHA-256 hash of the canonical JSON representation."""
        data = self.model_dump(mode="json")
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
