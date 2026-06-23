"""Pinata client for secondary IPFS pin replication.

Replicates audit trail pins to Pinata's managed pinning service using
the pin-by-CID endpoint. This ensures the audit trail remains fetchable
even if the primary IPFS node goes offline — a single point of failure
would otherwise break the reproducibility guarantee that validators and
auditors rely on.

Pinata's pin-by-CID endpoint tells Pinata to fetch an existing CID from
the IPFS network and hold onto it. No file re-upload, no new CID — the
content is identified by its hash.

``pin_directory`` is the complementary write path: it uploads the bytes
directly so Pinata adds the content itself and returns a fresh root CID. It is
the fallback used when the primary IPFS node cannot pin at all, so a primary
outage no longer aborts publication.
"""

import json
import logging
import time

import httpx

from scoring_service.config import settings

logger = logging.getLogger(__name__)

PIN_BY_CID_URL = "https://api.pinata.cloud/pinning/pinByHash"
PIN_FILE_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"

# Files are uploaded under a common folder so they stay addressable as
# `<root_cid>/<path>`, matching the primary node's wrap-with-directory layout.
# The folder name does not affect the root CID and never appears in access paths.
_PIN_DIRECTORY_WRAPPER = "bundle"


class PinataClient:
    """Replicates existing IPFS pins to Pinata via the pin-by-CID endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        self._api_key = api_key or settings.pinata_api_key
        self._api_secret = api_secret or settings.pinata_api_secret

        if not (self._api_key and self._api_secret):
            raise ValueError("PINATA_API_KEY and PINATA_API_SECRET are required")

        logger.info("Pinata client initialized")

    def pin_by_cid(self, cid: str, name: str | None = None) -> bool:
        """Request Pinata to pin an existing IPFS CID.

        Args:
            cid: The CID already pinned on the primary IPFS node.
            name: Optional human-readable name for the pin in Pinata's dashboard.

        Returns:
            True if Pinata accepted the pin request, False otherwise.
        """
        if not cid:
            logger.error("Cannot pin empty CID to Pinata")
            return False

        headers = {
            "pinata_api_key": self._api_key,
            "pinata_secret_api_key": self._api_secret,
            "Content-Type": "application/json",
        }

        payload: dict = {"hashToPin": cid}
        if name:
            payload["pinataMetadata"] = {"name": name}

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.http_request_timeout) as client:
                    response = client.post(PIN_BY_CID_URL, json=payload, headers=headers)
                    response.raise_for_status()
                    logger.info("Pinata pin-by-CID accepted — cid=%s", cid)
                    return True

            except (httpx.HTTPError, ValueError) as exc:
                if attempt == settings.http_max_retries:
                    logger.warning(
                        "Pinata pin_by_cid failed after %d attempts for cid=%s: %s",
                        settings.http_max_retries,
                        cid,
                        exc,
                    )
                    return False
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "Pinata pin_by_cid attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return False

    def pin_directory(self, files: dict[str, bytes], name: str | None = None) -> str | None:
        """Upload a directory of files directly to Pinata and return its root CID.

        Unlike pin-by-CID — which copies a CID that already exists on the network
        — this uploads the bytes, so Pinata adds the content itself. It is the
        write fallback for when the primary IPFS node pin fails. Files are sent
        under a common wrapper folder so Pinata always pins a *directory* (even a
        single-file bundle), mirroring the primary node's wrap-with-directory;
        ``pinFileToIPFS`` returns that wrapper directory's root CID, so files
        resolve at ``<root_cid>/<path>`` as consumers expect. The returned CID may
        differ from the primary node's for the same bytes; integrity is anchored
        by the artifact content hash, not the CID, so the two are interchangeable.

        Args:
            files: Mapping of relative paths to file contents.
            name: Optional human-readable name for the pin in Pinata's dashboard.

        Returns:
            Root CID of the uploaded directory, or None if all attempts fail.
        """
        if not files:
            logger.error("Cannot upload empty directory to Pinata")
            return None

        headers = {
            "pinata_api_key": self._api_key,
            "pinata_secret_api_key": self._api_secret,
        }
        data = {"pinataMetadata": json.dumps({"name": name})} if name else {}

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                multipart_files = [
                    ("file", (f"{_PIN_DIRECTORY_WRAPPER}/{path}", content))
                    for path, content in files.items()
                ]
                with httpx.Client(timeout=settings.http_request_timeout) as client:
                    response = client.post(
                        PIN_FILE_URL,
                        files=multipart_files,
                        data=data,
                        headers=headers,
                    )
                    response.raise_for_status()
                    root_cid = response.json().get("IpfsHash")

                if not root_cid:
                    logger.error("Pinata upload response missing IpfsHash")
                    return None

                logger.info(
                    "Pinata direct upload pinned %d files — root CID: %s",
                    len(files),
                    root_cid,
                )
                return root_cid

            except (httpx.HTTPError, ValueError) as exc:
                if attempt == settings.http_max_retries:
                    logger.warning(
                        "Pinata pin_directory failed after %d attempts: %s",
                        settings.http_max_retries,
                        exc,
                    )
                    return None
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "Pinata pin_directory attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return None
