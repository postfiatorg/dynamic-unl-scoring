"""Crawl client for validator IP resolution.

Probes each topology node's /crawl endpoint on port 2559 to extract
pubkey_validator, mapping validator master keys to their IP addresses.
"""

import logging
from typing import Optional

import httpx

from scoring_service.config import settings
from scoring_service.constants import PEER_PROTOCOL_PORT

logger = logging.getLogger(__name__)


class CrawlClient:
    """Resolves validator IPs by probing topology nodes' /crawl endpoints."""

    def __init__(self):
        self._client = httpx.Client(
            timeout=settings.http_request_timeout,
            verify=False,
        )

    def close(self):
        self._client.close()

    def _probe_node(self, ip: str, port: int) -> Optional[str]:
        """Probe a single node's /crawl endpoint. Returns pubkey_validator or None."""
        url = f"https://{ip}:{port}/crawl"
        try:
            response = self._client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("server", {}).get("pubkey_validator")
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Failed to probe %s — %s", url, exc)
            return None

    def resolve_validators(
        self, topology_nodes: list[dict], master_keys: set[str]
    ) -> dict[str, str]:
        """Probe each topology node's /crawl endpoint, return {master_key: ip}.

        Nodes that are unreachable, lack pubkey_validator, or aren't
        validators are skipped.
        """
        resolved: dict[str, str] = {}
        probed = 0

        for node in topology_nodes:
            ip = node.get("ip")
            if not ip:
                continue

            port = node.get("port") or PEER_PROTOCOL_PORT
            probed += 1
            pubkey = self._probe_node(ip, port)

            if pubkey and pubkey in master_keys:
                resolved[pubkey] = ip
                logger.info("Resolved validator %s → %s", pubkey[:12] + "...", ip)

        logger.info(
            "Resolved %d/%d validator IPs from %d topology nodes probed",
            len(resolved),
            len(master_keys),
            probed,
        )
        return resolved
