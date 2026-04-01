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
from scoring_service.clients.geoip import GeoIPClient
from scoring_service.clients.vhs import VHSClient
from scoring_service.database import get_db
from scoring_service.models import ScoringSnapshot

logger = logging.getLogger(__name__)

SOURCES = {
    "vhs_validators": True,
    "vhs_topology": True,
    "crawl_probes": True,
    "asn_lookups": True,
    "maxmind_responses": False,
}


def _content_hash(data: object) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        geoip_client: GeoIPClient | None = None,
    ):
        self._vhs = vhs_client or VHSClient()
        self._crawl = crawl_client or CrawlClient()
        self._asn = asn_client or ASNClient()
        self._geoip = geoip_client or GeoIPClient()

    def collect(self, round_number: int, network: str) -> ScoringSnapshot:
        """Run the full collection sequence and return a ScoringSnapshot."""
        connection = get_db()

        try:
            # 1. Fetch validators and topology from VHS
            validators, raw_validators = self._vhs.fetch_validators()
            if raw_validators:
                _save_raw_evidence(
                    connection, round_number, "vhs_validators",
                    raw_validators, SOURCES["vhs_validators"],
                )

            topology, raw_topology = self._vhs.fetch_topology()
            if raw_topology:
                _save_raw_evidence(
                    connection, round_number, "vhs_topology",
                    raw_topology, SOURCES["vhs_topology"],
                )

            # 2. Resolve validator IPs via /crawl
            master_keys = {v.master_key for v in validators}
            resolved_ips, raw_probes = self._crawl.resolve_validators(topology, master_keys)
            for validator in validators:
                validator.ip = resolved_ips.get(validator.master_key)

            if raw_probes:
                _save_raw_evidence(
                    connection, round_number, "crawl_probes",
                    raw_probes, SOURCES["crawl_probes"],
                )

            # 3. Enrich with ASN data
            raw_asn = self._asn.enrich_validators(validators)
            if raw_asn:
                _save_raw_evidence(
                    connection, round_number, "asn_lookups",
                    raw_asn, SOURCES["asn_lookups"],
                )

            # 4. Enrich with geolocation
            raw_geoip = self._geoip.enrich_validators(validators)
            if raw_geoip:
                _save_raw_evidence(
                    connection, round_number, "maxmind_responses",
                    raw_geoip, SOURCES["maxmind_responses"],
                )

            connection.commit()
            logger.info("Raw evidence archived for round %d", round_number)

        except Exception:
            connection.rollback()
            logger.exception("Collection failed for round %d", round_number)
            raise
        finally:
            connection.close()

        # 5. Assemble snapshot
        snapshot = ScoringSnapshot(
            round_number=round_number,
            network=network,
            snapshot_timestamp=datetime.now(timezone.utc),
            validators=validators,
        )

        logger.info(
            "Snapshot assembled: round=%d, validators=%d, hash=%s",
            round_number,
            len(validators),
            snapshot.content_hash()[:12] + "...",
        )
        return snapshot
