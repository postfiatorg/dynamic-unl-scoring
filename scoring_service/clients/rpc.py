"""RPC client for fetching validator manifests from a postfiatd node.

The manifest command returns the raw base64-encoded STObject binary that
binds a validator's master key to its ephemeral signing key. This blob
is required for VL assembly — VHS does not expose it.
"""

import logging
import time

import httpx

from scoring_service.config import settings

logger = logging.getLogger(__name__)


class RPCClient:
    """Thin client for postfiatd JSON-RPC calls."""

    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = rpc_url or settings.rpc_url
        if not self.rpc_url:
            raise ValueError("RPC_URL is required for manifest fetching")

    def _call(self, method: str, params: dict | None = None) -> dict | None:
        """Execute a JSON-RPC call with retry logic."""
        payload = {"method": method, "params": [params or {}]}

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.http_request_timeout) as client:
                    response = client.post(
                        self.rpc_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data.get("result", {})
                    if result.get("error"):
                        logger.error(
                            "RPC %s error: %s — %s",
                            method,
                            result["error"],
                            result.get("error_message", ""),
                        )
                        return None
                    return result
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == settings.http_max_retries:
                    logger.error(
                        "RPC %s failed after %d attempts: %s",
                        method,
                        settings.http_max_retries,
                        exc,
                    )
                    return None
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "RPC %s attempt %d/%d failed: %s — retrying in %ds",
                    method,
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        return None

    def fetch_manifest(self, public_key: str) -> str | None:
        """Fetch the raw base64 manifest for a validator.

        Args:
            public_key: Validator master key (base58).

        Returns:
            Base64-encoded manifest blob, or None if not found.
        """
        result = self._call("manifest", {"public_key": public_key})
        if result is None:
            return None

        manifest = result.get("manifest")
        if not manifest:
            logger.warning("No manifest returned for %s", public_key)
            return None

        return manifest

    def fetch_manifests(self, public_keys: list[str]) -> dict[str, str]:
        """Fetch manifests for multiple validators.

        Args:
            public_keys: List of validator master keys (base58).

        Returns:
            Dict mapping master_key → base64 manifest. Keys with no
            manifest are omitted.
        """
        manifests = {}
        for key in public_keys:
            manifest = self.fetch_manifest(key)
            if manifest:
                manifests[key] = manifest
            else:
                logger.warning("Skipping validator %s — manifest not available", key)
        return manifests
