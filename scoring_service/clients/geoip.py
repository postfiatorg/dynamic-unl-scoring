"""MaxMind GeoIP2 client for validator geolocation.

Resolves validator IP addresses to geographic locations (continent, country,
region, city) using the MaxMind GeoIP2 Precision Insights web service.

IMPORTANT: MaxMind EULA prohibits republishing extracted data points. The
geolocation data produced by this client is for internal LLM scoring
consumption only and must never be included in IPFS audit trail publications.
"""

import logging
from typing import Optional

import geoip2.errors
import geoip2.webservice

from scoring_service.config import settings
from scoring_service.models import GeoLocation, ValidatorProfile

logger = logging.getLogger(__name__)


class GeoIPClient:
    """Resolves IP addresses to geographic locations via MaxMind GeoIP2.

    Operates in no-op mode when credentials are not configured, returning
    None for all lookups. This is the normal state in dev/CI environments.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        license_key: Optional[str] = None,
    ):
        account_id = account_id or settings.maxmind_account_id
        license_key = license_key or settings.maxmind_license_key

        if account_id and license_key:
            self._client = geoip2.webservice.Client(
                int(account_id), license_key,
            )
            logger.info("MaxMind GeoIP2 client initialized")
        else:
            self._client = None
            logger.info("MaxMind credentials not configured — geolocation disabled")

    def close(self):
        if self._client:
            self._client.close()

    def lookup(self, ip: Optional[str]) -> Optional[GeoLocation]:
        """Look up geolocation for a single IP. Returns None for null IPs."""
        if not ip:
            return None

        if not self._client:
            return None

        try:
            response = self._client.insights(ip)
            return GeoLocation(
                continent=response.continent.name,
                country=response.country.name,
                region=response.subdivisions.most_specific.name if response.subdivisions else None,
                city=response.city.name,
            )
        except geoip2.errors.AddressNotFoundError:
            logger.warning("No geolocation data for %s", ip)
            return GeoLocation()
        except geoip2.errors.AuthenticationError as exc:
            logger.error("MaxMind authentication failed — %s", exc)
            return GeoLocation()
        except geoip2.errors.GeoIP2Error as exc:
            logger.warning("MaxMind lookup failed for %s — %s", ip, exc)
            return GeoLocation()

    def enrich_validators(self, validators: list[ValidatorProfile]) -> None:
        """Attach geolocation to each validator that has a resolved IP."""
        resolved = 0
        for validator in validators:
            result = self.lookup(validator.ip)
            validator.geolocation = result
            if result and result.country:
                resolved += 1

        logger.info(
            "Geolocation enrichment: %d/%d validators resolved",
            resolved,
            len(validators),
        )
