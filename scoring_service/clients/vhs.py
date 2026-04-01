"""VHS data collection client for the scoring pipeline.

Fetches validator performance data and network topology from the Validator
History Service API.
"""

import logging
import time
from typing import Optional

import httpx

from scoring_service.config import settings
from scoring_service.models import (
    AgreementScore,
    ValidatorProfile,
)

logger = logging.getLogger(__name__)


def _request_with_retry(client: httpx.Client, url: str) -> Optional[dict]:
    """GET request with exponential backoff. Returns parsed JSON or None."""
    for attempt in range(1, settings.http_max_retries + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == settings.http_max_retries:
                logger.error("VHS request failed after %d attempts: %s — %s", settings.http_max_retries, url, exc)
                return None
            delay = settings.http_retry_base_delay ** attempt
            logger.warning("VHS request attempt %d/%d failed: %s — retrying in %ds", attempt, settings.http_max_retries, exc, delay)
            time.sleep(delay)
    return None


def _parse_agreement(raw: dict) -> AgreementScore:
    return AgreementScore(
        score=raw.get("score"),
        total=raw.get("total"),
        missed=raw.get("missed"),
    )


def _parse_validator(raw: dict) -> ValidatorProfile:
    master_key = raw.get("master_key") or raw.get("validation_public_key", "")
    signing_key = raw.get("signing_key") or raw.get("validation_public_key", "")

    unl_value = raw.get("unl", False)
    unl = bool(unl_value)

    return ValidatorProfile(
        master_key=master_key,
        signing_key=signing_key,
        domain=raw.get("domain") or None,
        domain_verified=raw.get("domain_verified"),
        agreement_1h=_parse_agreement(raw.get("agreement_1h", {})),
        agreement_24h=_parse_agreement(raw.get("agreement_24h", {})),
        agreement_30d=_parse_agreement(raw.get("agreement_30day", {})),
        server_version=raw.get("server_version", ""),
        unl=unl,
        base_fee=raw.get("base_fee"),
    )


def _normalize_list(data: object) -> list[dict]:
    """VHS returns either a list or a dict of objects — normalize to list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


class VHSClient:
    """Fetches validator and network data from the Validator History Service."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.vhs_api_url).rstrip("/")
        self._client = httpx.Client(timeout=settings.http_request_timeout)

    def close(self):
        self._client.close()

    def fetch_validators(self) -> tuple[list[ValidatorProfile], dict | None]:
        """Fetch validators from VHS. Returns (parsed validators, raw JSON response)."""
        url = f"{self.base_url}/v1/network/validators"
        data = _request_with_retry(self._client, url)
        if data is None:
            return [], None

        raw_validators = _normalize_list(data.get("validators", []))
        validators = [_parse_validator(v) for v in raw_validators]
        validators.sort(key=lambda v: v.master_key)
        logger.info("Fetched %d validators from VHS", len(validators))
        return validators, data

    def fetch_topology(self) -> tuple[list[dict], dict | None]:
        """Fetch topology nodes from VHS. Returns (parsed nodes, raw JSON response)."""
        url = f"{self.base_url}/v1/network/topology/nodes"
        data = _request_with_retry(self._client, url)
        if data is None:
            return [], None

        raw_nodes = _normalize_list(data.get("nodes", []))
        nodes = [
            {
                "ip": n.get("ip"),
                "port": n.get("port"),
                "node_public_key": n.get("node_public_key", ""),
            }
            for n in raw_nodes
        ]
        nodes.sort(key=lambda n: n["node_public_key"])
        logger.info("Fetched %d topology nodes from VHS", len(nodes))
        return nodes, data

