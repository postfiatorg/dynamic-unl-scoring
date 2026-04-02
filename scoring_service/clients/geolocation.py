"""DB-IP Lite client for validator country-level geolocation.

Resolves validator IP addresses to countries using the DB-IP Lite
Country database (MMDB format, CC BY 4.0). Results are freely
publishable with attribution: "IP geolocation by DB-IP.com"
"""

import logging
from pathlib import Path
from typing import Optional

import maxminddb

from scoring_service.config import settings
from scoring_service.models import GeoLocation, ValidatorProfile

logger = logging.getLogger(__name__)

DBIP_PATH = Path(settings.geolocation_db_path)


class GeolocationClient:
    """Resolves IP addresses to countries via DB-IP Lite local database."""

    def __init__(self, db_path: Optional[str] = None):
        path = Path(db_path) if db_path else DBIP_PATH

        if path.exists():
            self._reader = maxminddb.open_database(str(path))
            logger.info("DB-IP Lite reader initialized — %s", path)
        else:
            self._reader = None
            logger.warning("DB-IP database not found at %s — geolocation disabled", path)

    def close(self):
        if self._reader:
            self._reader.close()

    def lookup(self, ip: Optional[str]) -> Optional[GeoLocation]:
        """Look up country for a single IP. Returns None for null IPs."""
        if not ip:
            return None

        if not self._reader:
            return None

        try:
            record = self._reader.get(ip)
            if not isinstance(record, dict):
                logger.warning("No geolocation data for %s", ip)
                return GeoLocation()

            country_names: dict = record.get("country", {}).get("names", {})  # type: ignore[union-attr]

            return GeoLocation(
                country=str(country_names.get("en")) if country_names.get("en") else None,
            )
        except Exception as exc:
            logger.warning("DB-IP lookup failed for %s — %s", ip, exc)
            return GeoLocation()

    def enrich_validators(self, validators: list[ValidatorProfile]) -> dict:
        """Attach geolocation to each validator that has a resolved IP.

        Returns raw lookup results as {ip: {country}} for archival.
        """
        resolved = 0
        raw_lookups: dict = {}
        for validator in validators:
            result = self.lookup(validator.ip)
            validator.geolocation = result
            if validator.ip:
                raw_lookups[validator.ip] = result.model_dump() if result else None
            if result and result.country:
                resolved += 1

        logger.info(
            "Geolocation enrichment: %d/%d validators resolved",
            resolved,
            len(validators),
        )
        return raw_lookups
