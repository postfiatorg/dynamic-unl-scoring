"""IPFS client for pinning audit trail artifacts.

Uploads files and directories to the foundation's self-hosted IPFS node
via the HTTP API (/api/v0/add). Returns Content Identifiers (CIDs) that
allow anyone to retrieve and verify the data from any IPFS gateway.
"""

import json
import logging
import time

import httpx

from scoring_service.config import settings

logger = logging.getLogger(__name__)


class IPFSClient:
    """Pins files and directories to an IPFS node via the HTTP API."""

    def __init__(
        self,
        api_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.api_url = (api_url or settings.ipfs_api_url).rstrip("/")
        if not self.api_url:
            raise ValueError("IPFS_API_URL is required but not configured")

        self._username = username or settings.ipfs_api_username
        self._password = password or settings.ipfs_api_password

        self._auth = None
        if self._username and self._password:
            self._auth = httpx.BasicAuth(self._username, self._password)

        logger.info("IPFS client initialized — endpoint: %s", self.api_url)

    def pin_file(self, name: str, content: bytes) -> str | None:
        """Pin a single file to IPFS.

        Args:
            name: Filename (used as IPFS object name).
            content: Raw file bytes.

        Returns:
            CID of the pinned file, or None if all attempts fail.
        """
        url = f"{self.api_url}/api/v0/add"

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.http_request_timeout, auth=self._auth) as client:
                    response = client.post(
                        url,
                        files={"file": (name, content)},
                    )
                    response.raise_for_status()
                    data = response.json()
                    cid = data.get("Hash")
                    if not cid:
                        logger.error("IPFS add response missing Hash field: %s", data)
                        return None
                    logger.info("Pinned file %s — CID: %s", name, cid)
                    return cid

            except (httpx.HTTPError, ValueError) as exc:
                if attempt == settings.http_max_retries:
                    logger.error(
                        "IPFS pin_file failed after %d attempts: %s",
                        settings.http_max_retries,
                        exc,
                    )
                    return None
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "IPFS pin_file attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return None

    def pin_directory(self, files: dict[str, bytes]) -> str | None:
        """Pin a directory of files to IPFS in a single atomic request.

        Uploads all files as a wrapped directory using the IPFS add API's
        wrap-with-directory option. Each file is sent as a multipart part
        with its relative path. The API returns newline-delimited JSON —
        one object per file plus a final object for the directory root
        (identified by an empty Name).

        Args:
            files: Mapping of relative paths to file contents.
                   Example: {"raw/vhs_validators.json": b'[...]', "metadata.json": b'{...}'}

        Returns:
            Root CID of the pinned directory, or None if all attempts fail.
        """
        if not files:
            logger.error("Cannot pin empty directory")
            return None

        url = f"{self.api_url}/api/v0/add?wrap-with-directory=true"

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                multipart_files = [
                    ("file", (path, content))
                    for path, content in files.items()
                ]

                with httpx.Client(timeout=settings.http_request_timeout, auth=self._auth) as client:
                    response = client.post(url, files=multipart_files)
                    response.raise_for_status()

                root_cid = _parse_directory_response(response.text)
                if not root_cid:
                    logger.error("Failed to extract root CID from IPFS response")
                    return None

                logger.info(
                    "Pinned directory (%d files) — root CID: %s",
                    len(files),
                    root_cid,
                )
                return root_cid

            except (httpx.HTTPError, ValueError) as exc:
                if attempt == settings.http_max_retries:
                    logger.error(
                        "IPFS pin_directory failed after %d attempts: %s",
                        settings.http_max_retries,
                        exc,
                    )
                    return None
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "IPFS pin_directory attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return None


def _parse_directory_response(body: str) -> str | None:
    """Extract the root directory CID from a newline-delimited JSON response.

    The IPFS add API with wrap-with-directory returns one JSON object per
    line. Each file gets an entry with its path in the Name field. The
    final entry has an empty Name and contains the root directory CID.
    """
    root_cid = None
    for line in body.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed IPFS response line: %s", line)
            continue
        if entry.get("Name") == "":
            root_cid = entry.get("Hash")
    return root_cid
