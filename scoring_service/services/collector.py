"""Data collector service for the scoring pipeline.

Orchestrates all data collection clients, archives raw evidence, and
assembles a complete ScoringSnapshot for the LLM scorer.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from scoring_service.clients.asn import ASNClient
from scoring_service.clients.crawl import CrawlClient
from scoring_service.clients.geolocation import GeolocationClient
from scoring_service.clients.vhs import VHSClient
from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.models import ScoringSnapshot, ValidatorProfile
from scoring_service.services.dry_runs import store_dry_run_raw_evidence

logger = logging.getLogger(__name__)

SOURCES = {
    "vhs_validators": True,
    "vhs_topology": True,
    "crawl_probes": True,
    "asn_lookups": True,
    "geoip_lookups": True,
}


def _content_hash(data: object) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _server_version_key(server_version: object) -> str:
    return str(server_version).strip() if server_version is not None else ""


def _filter_eligible_validators(
    validators: list[ValidatorProfile],
    excluded_server_versions: frozenset[str],
) -> tuple[list[ValidatorProfile], list[ValidatorProfile]]:
    """Return validators eligible for scoring and those excluded by version."""
    if not excluded_server_versions:
        return validators, []

    eligible: list[ValidatorProfile] = []
    excluded: list[ValidatorProfile] = []

    for validator in validators:
        if _server_version_key(validator.server_version) in excluded_server_versions:
            excluded.append(validator)
        else:
            eligible.append(validator)

    return eligible, excluded


def _save_raw_evidence(
    connection,
    round_number: int,
    source: str,
    raw_data: object,
    publishable: bool,
) -> None:
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO raw_evidence (round_number, source, raw_data, content_hash, publishable)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            round_number,
            source,
            json.dumps(raw_data, default=str),
            _content_hash(raw_data),
            publishable,
        ),
    )
    cursor.close()


class DataCollectorService:
    """Orchestrates data collection and raw evidence archival."""

    def __init__(
        self,
        vhs_client: VHSClient | None = None,
        crawl_client: CrawlClient | None = None,
        asn_client: ASNClient | None = None,
        geoip_client: GeolocationClient | None = None,
    ):
        self._vhs = vhs_client or VHSClient()
        self._crawl = crawl_client or CrawlClient()
        self._asn = asn_client or ASNClient()
        self._geoip = geoip_client or GeolocationClient()

    def _collect(
        self,
        identifier: int,
        network: str,
        save_raw_evidence,
        log_context: str,
    ) -> tuple[ScoringSnapshot, dict[str, object]]:
        """Run the full collection sequence and return a snapshot plus raw evidence."""
        connection = get_db()
        raw_evidence: dict[str, object] = {}

        try:
            # 1. Fetch validators and topology from VHS
            validators, raw_validators = self._vhs.fetch_validators()
            if raw_validators is None:
                raise RuntimeError("VHS validators response unavailable")
            if raw_validators is not None:
                save_raw_evidence(
                    connection, identifier, "vhs_validators",
                    raw_validators, SOURCES["vhs_validators"],
                )
                raw_evidence["vhs_validators"] = raw_validators

            validators, excluded_validators = _filter_eligible_validators(
                validators,
                settings.excluded_validator_server_version_set,
            )
            if excluded_validators:
                logger.info(
                    "Excluded %d validator(s) from scoring due to server_version policy: %s",
                    len(excluded_validators),
                    sorted(settings.excluded_validator_server_version_set),
                )

            topology, raw_topology = self._vhs.fetch_topology()
            if raw_topology is None:
                raise RuntimeError("VHS topology response unavailable")
            if raw_topology is not None:
                save_raw_evidence(
                    connection, identifier, "vhs_topology",
                    raw_topology, SOURCES["vhs_topology"],
                )
                raw_evidence["vhs_topology"] = raw_topology

            # 2. Resolve validator IPs via /crawl
            master_keys = {v.master_key for v in validators}
            resolved_ips, raw_probes = self._crawl.resolve_validators(topology, master_keys)
            for validator in validators:
                validator.ip = resolved_ips.get(validator.master_key)

            if raw_probes:
                save_raw_evidence(
                    connection, identifier, "crawl_probes",
                    raw_probes, SOURCES["crawl_probes"],
                )
                raw_evidence["crawl_probes"] = raw_probes

            # 3. Enrich with ASN data
            raw_asn = self._asn.enrich_validators(validators)
            if raw_asn:
                save_raw_evidence(
                    connection, identifier, "asn_lookups",
                    raw_asn, SOURCES["asn_lookups"],
                )
                raw_evidence["asn_lookups"] = raw_asn

            # 4. Enrich with geolocation
            raw_geoip = self._geoip.enrich_validators(validators)
            if raw_geoip:
                save_raw_evidence(
                    connection, identifier, "geoip_lookups",
                    raw_geoip, SOURCES["geoip_lookups"],
                )
                raw_evidence["geoip_lookups"] = raw_geoip

            connection.commit()
            logger.info("Raw evidence archived for %s %d", log_context, identifier)

        except Exception:
            connection.rollback()
            logger.exception("Collection failed for %s %d", log_context, identifier)
            raise
        finally:
            connection.close()

        # 5. Assemble snapshot
        snapshot = ScoringSnapshot(
            round_number=identifier,
            network=network,
            snapshot_timestamp=datetime.now(timezone.utc),
            validators=validators,
        )

        logger.info(
            "Snapshot assembled: %s=%d, validators=%d, hash=%s",
            log_context,
            identifier,
            len(validators),
            snapshot.content_hash()[:12] + "...",
        )
        return snapshot, raw_evidence

    def collect(self, round_number: int, network: str) -> ScoringSnapshot:
        """Run the full public collection sequence and return a ScoringSnapshot."""
        snapshot, _raw_evidence = self._collect(
            identifier=round_number,
            network=network,
            save_raw_evidence=_save_raw_evidence,
            log_context="round",
        )
        return snapshot

    def collect_dry_run(
        self,
        dry_run_id: int,
        network: str,
    ) -> tuple[ScoringSnapshot, dict[str, object]]:
        """Run collection for a private dry-run without public raw evidence rows."""
        return self._collect(
            identifier=dry_run_id,
            network=network,
            save_raw_evidence=store_dry_run_raw_evidence,
            log_context="dry_run",
        )
