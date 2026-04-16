"""IPFS audit trail assembly and publication service.

Assembles the complete evidence chain from a scoring round into a
structured directory, pins it to IPFS, and stores the files in
PostgreSQL for HTTPS fallback serving.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from scoring_service.clients.ipfs import IPFSClient
from scoring_service.clients.pinata import PinataClient
from scoring_service.config import settings
from scoring_service.models import ScoringSnapshot
from scoring_service.services.response_parser import ScoringResult
from scoring_service.services.unl_selector import UNLSelectionResult

logger = logging.getLogger(__name__)

GEOLOCATION_ATTRIBUTION = "IP geolocation by DB-IP.com"
PROMPT_VERSION = "v2"


def _content_hash(data: object) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _serialize(data: object) -> bytes:
    return json.dumps(data, indent=2, sort_keys=True, default=str).encode()


def _build_scoring_config(scored_at: datetime) -> dict:
    return {
        "model_id": settings.scoring_model_id,
        "model_name": settings.scoring_model_name,
        "model_source": f"https://huggingface.co/{settings.scoring_model_id}",
        "prompt_version": PROMPT_VERSION,
        "temperature": settings.scoring_temperature,
        "max_tokens": settings.scoring_max_tokens,
        "scored_at": scored_at.isoformat(),
    }


def _build_scores(scoring_result: ScoringResult) -> dict:
    return {
        "validator_scores": [
            {
                "master_key": v.master_key,
                "score": v.score,
                "consensus": v.consensus,
                "reliability": v.reliability,
                "software": v.software,
                "diversity": v.diversity,
                "identity": v.identity,
                "reasoning": v.reasoning,
            }
            for v in scoring_result.validator_scores
        ],
        "network_summary": scoring_result.network_summary,
    }


def _build_unl(unl_result: UNLSelectionResult) -> dict:
    return {
        "unl": unl_result.unl,
        "alternates": unl_result.alternates,
    }


def _build_metadata(
    round_number: int,
    file_hashes: dict[str, str],
    ipfs_cid: str | None,
    published_at: datetime,
    gateway_urls: list[str] | None = None,
    override: dict | None = None,
) -> dict:
    metadata: dict = {
        "round_number": round_number,
        "published_at": published_at.isoformat(),
        "geolocation_attribution": GEOLOCATION_ATTRIBUTION,
        "ipfs_cid": ipfs_cid,
        "gateway_urls": gateway_urls or [],
        "file_hashes": file_hashes,
    }
    if override is not None:
        metadata["override"] = override
    return metadata


def _build_override_unl(master_keys: list[str]) -> dict:
    return {
        "unl": master_keys,
        "alternates": [],
    }


def _collect_gateway_urls() -> list[str]:
    gateways = []
    if settings.ipfs_gateway_url:
        gateways.append(settings.ipfs_gateway_url.rstrip("/"))
    if settings.pinata_gateway_url:
        gateways.append(settings.pinata_gateway_url.rstrip("/"))
    return gateways


def _store_audit_trail_files(
    conn,
    round_number: int,
    files: dict[str, Any],
) -> None:
    cursor = conn.cursor()
    for file_path, content in files.items():
        cursor.execute(
            """
            INSERT INTO audit_trail_files (round_number, file_path, content)
            VALUES (%s, %s, %s)
            ON CONFLICT (round_number, file_path) DO UPDATE SET
                content = EXCLUDED.content,
                created_at = now()
            """,
            (round_number, file_path, json.dumps(content, sort_keys=True, default=str)),
        )
    cursor.close()


def get_audit_trail_file(conn, round_number: int, file_path: str) -> dict | None:
    """Retrieve a single audit trail file from the database."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT content FROM audit_trail_files WHERE round_number = %s AND file_path = %s",
        (round_number, file_path),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


class IPFSPublisherService:
    """Assembles and publishes the scoring round audit trail."""

    def __init__(
        self,
        ipfs_client: IPFSClient | None = None,
        pinata_client: PinataClient | None = None,
    ):
        self._ipfs = ipfs_client or IPFSClient()
        if pinata_client is not None:
            self._pinata = pinata_client
        elif settings.pinata_enabled:
            self._pinata = PinataClient()
        else:
            self._pinata = None
            logger.info("Pinata secondary pinning disabled — credentials not configured")

    def publish(
        self,
        round_number: int,
        snapshot: ScoringSnapshot,
        raw_evidence: dict[str, Any],
        scoring_result: ScoringResult,
        unl_result: UNLSelectionResult,
        signed_vl: dict[str, Any],
        conn,
    ) -> str | None:
        """Assemble the audit trail, pin to IPFS, and store for HTTPS fallback.

        Args:
            round_number: Scoring round number.
            snapshot: Assembled validator data snapshot.
            raw_evidence: Mapping of source names to raw data dicts
                (vhs_validators, vhs_topology, crawl_probes, asn_lookups, geoip_lookups).
            scoring_result: Parsed LLM scoring output.
            unl_result: UNL selection result (selected + alternates).
            signed_vl: The signed Validator List JSON (v2 format).
            conn: Database connection for atomic CID and file storage.

        Returns:
            Root CID of the pinned directory, or None if IPFS pinning failed.
        """
        published_at = datetime.now(timezone.utc)

        snapshot_data = json.loads(snapshot.model_dump_json())
        scoring_config = _build_scoring_config(published_at)
        scores = _build_scores(scoring_result)
        unl = _build_unl(unl_result)

        assembled: dict[str, Any] = {
            "snapshot.json": snapshot_data,
            "scoring_config.json": scoring_config,
            "scores.json": scores,
            "unl.json": unl,
            "vl.json": signed_vl,
        }

        for source_name, raw_data in raw_evidence.items():
            assembled[f"raw/{source_name}.json"] = raw_data

        file_hashes = {
            path: _content_hash(content)
            for path, content in sorted(assembled.items())
        }

        ipfs_files = {
            path: _serialize(content)
            for path, content in assembled.items()
        }

        root_cid = self._ipfs.pin_directory(ipfs_files)

        metadata = _build_metadata(
            round_number,
            file_hashes,
            root_cid,
            published_at,
            gateway_urls=_collect_gateway_urls(),
        )
        assembled["metadata.json"] = metadata
        ipfs_files["metadata.json"] = _serialize(metadata)

        if root_cid is None:
            logger.error("IPFS pinning failed for round %d", round_number)
            return None

        if self._pinata is not None:
            pin_name = f"dynamic-unl-scoring-round-{round_number}"
            if not self._pinata.pin_by_cid(root_cid, name=pin_name):
                logger.warning(
                    "Pinata secondary pin failed for round %d (cid=%s) — "
                    "primary pin is source of truth, round will proceed",
                    round_number,
                    root_cid,
                )

        try:
            _store_audit_trail_files(conn, round_number, assembled)
            conn.commit()
            logger.info(
                "Audit trail published: round=%d, cid=%s, files=%d",
                round_number,
                root_cid,
                len(assembled),
            )
        except Exception:
            conn.rollback()
            logger.exception("Failed to store audit trail files for round %d", round_number)
            raise

        return root_cid

    def publish_override(
        self,
        round_number: int,
        master_keys: list[str],
        signed_vl: dict[str, Any],
        override_type: str,
        override_reason: str,
        conn,
    ) -> str | None:
        """Assemble and pin the audit trail for an admin override round.

        Override rounds have no collected snapshot, no LLM scores, and no
        selector evidence — the UNL was supplied by an operator. The
        directory therefore contains only `unl.json`, `vl.json`, and
        `metadata.json`, with the metadata carrying an `override` block
        that records type and reason.
        """
        published_at = datetime.now(timezone.utc)
        unl = _build_override_unl(master_keys)

        assembled: dict[str, Any] = {
            "unl.json": unl,
            "vl.json": signed_vl,
        }

        file_hashes = {
            path: _content_hash(content)
            for path, content in sorted(assembled.items())
        }

        ipfs_files = {
            path: _serialize(content)
            for path, content in assembled.items()
        }

        root_cid = self._ipfs.pin_directory(ipfs_files)

        metadata = _build_metadata(
            round_number,
            file_hashes,
            root_cid,
            published_at,
            gateway_urls=_collect_gateway_urls(),
            override={
                "type": override_type,
                "reason": override_reason,
            },
        )
        assembled["metadata.json"] = metadata
        ipfs_files["metadata.json"] = _serialize(metadata)

        if root_cid is None:
            logger.error("IPFS pinning failed for override round %d", round_number)
            return None

        if self._pinata is not None:
            pin_name = f"dynamic-unl-scoring-override-round-{round_number}"
            if not self._pinata.pin_by_cid(root_cid, name=pin_name):
                logger.warning(
                    "Pinata secondary pin failed for override round %d (cid=%s) — "
                    "primary pin is source of truth, override will proceed",
                    round_number,
                    root_cid,
                )

        try:
            _store_audit_trail_files(conn, round_number, assembled)
            conn.commit()
            logger.info(
                "Override audit trail published: round=%d, cid=%s, type=%s",
                round_number,
                root_cid,
                override_type,
            )
        except Exception:
            conn.rollback()
            logger.exception(
                "Failed to store override audit trail files for round %d", round_number
            )
            raise

        return root_cid
