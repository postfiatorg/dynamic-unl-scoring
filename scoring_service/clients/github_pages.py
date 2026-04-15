"""GitHub Pages client for canonical VL distribution.

Commits each round's freshly signed Validator List to the repository that
backs `postfiat.org/{env}_vl.json` (`postfiatorg/postfiatorg.github.io`),
so validators polling that URL pick up the new blob on their next
`[validator_list_sites]` refresh.

Uses the GitHub Contents API, which performs the write as a single HTTP
request — no git binary, no SSH key, no working tree. Each publish is a
GET (to fetch the current file SHA, required for optimistic concurrency)
followed by a PUT (to replace the file with the new content). The
authenticated identity is a fine-grained PAT scoped to contents:write on
the single target repo.

Edge cases handled:
    - 404 on the GET — file does not yet exist; PUT without a `sha`
      parameter and GitHub creates it.
    - 409 on the PUT — SHA mismatch from an interleaving commit; retry
      the full GET/PUT cycle with exponential backoff.
    - 5xx / network errors on either call — retry with exponential
      backoff up to `http_max_retries`.
    - 4xx other than 409/404 — fail-fast (auth failure, invalid path,
      unknown repo).
"""

import base64
import logging
import time

import httpx
from fastapi import status

from scoring_service.config import settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GitHubPagesError(RuntimeError):
    """Raised when a Pages publish fails after exhausting retries."""


class GitHubPagesClient:
    """Commits files to a GitHub Pages repository via the Contents API."""

    def __init__(
        self,
        token: str | None = None,
        repo: str | None = None,
        file_path: str | None = None,
        branch: str | None = None,
        commit_author_name: str | None = None,
        commit_author_email: str | None = None,
    ):
        self._token = token or settings.github_pages_token
        self._repo = repo or settings.github_pages_repo
        self._file_path = file_path or settings.github_pages_file_path
        self._branch = branch or settings.github_pages_branch
        self._author_name = commit_author_name or settings.github_pages_commit_author_name
        self._author_email = commit_author_email or settings.github_pages_commit_author_email

        if not self._token:
            raise ValueError("GITHUB_PAGES_TOKEN is required for VL distribution")
        if not self._repo:
            raise ValueError("GITHUB_PAGES_REPO is required for VL distribution")
        if not self._file_path:
            raise ValueError("GITHUB_PAGES_FILE_PATH is required for VL distribution")

        logger.info(
            "GitHub Pages client initialized: repo=%s, path=%s, branch=%s",
            self._repo,
            self._file_path,
            self._branch,
        )

    @property
    def _contents_url(self) -> str:
        return f"{GITHUB_API_BASE}/repos/{self._repo}/contents/{self._file_path}"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def publish(self, content: str, commit_message: str) -> str:
        """Commit `content` to the configured file path.

        Args:
            content: UTF-8 file content. Base64 encoding is handled
                internally — pass the raw JSON string, not the encoded
                form.
            commit_message: Commit message written to the Pages repo.

        Returns:
            HTML URL of the produced commit, suitable for persisting
            alongside the round record for audit-trail cross-reference.

        Raises:
            GitHubPagesError: When the Contents API rejects the publish
                after exhausting retries, or when fail-fast 4xx
                responses indicate a configuration problem.
        """
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                sha = self._fetch_sha()
                commit_url = self._put_content(content_b64, commit_message, sha)
                logger.info(
                    "GitHub Pages publish succeeded: repo=%s path=%s commit=%s",
                    self._repo,
                    self._file_path,
                    commit_url,
                )
                return commit_url

            except _ConflictError as exc:
                if attempt == settings.http_max_retries:
                    raise GitHubPagesError(
                        f"GitHub Pages publish failed after {settings.http_max_retries} "
                        f"attempts due to persistent SHA conflicts: {exc}"
                    ) from exc
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "GitHub Pages PUT attempt %d/%d returned 409 (SHA conflict); "
                    "refetching SHA and retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    delay,
                )
                time.sleep(delay)

            except _TransientError as exc:
                if attempt == settings.http_max_retries:
                    raise GitHubPagesError(
                        f"GitHub Pages publish failed after {settings.http_max_retries} "
                        f"attempts due to transient errors: {exc}"
                    ) from exc
                delay = settings.http_retry_base_delay ** attempt
                logger.warning(
                    "GitHub Pages publish attempt %d/%d hit a transient error "
                    "(%s); retrying in %ds",
                    attempt,
                    settings.http_max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise GitHubPagesError("GitHub Pages publish exhausted retries without a definitive outcome")

    def _fetch_sha(self) -> str | None:
        """Return the current file SHA, or None if the file does not yet exist.

        Raises:
            GitHubPagesError: On a 4xx other than 404, or on any response
                that cannot be recovered from via retry.
            _TransientError: On 5xx or network errors (retryable).
        """
        params = {"ref": self._branch}

        try:
            with httpx.Client(timeout=settings.http_request_timeout) as client:
                response = client.get(self._contents_url, headers=self._headers, params=params)
        except httpx.HTTPError as exc:
            raise _TransientError(f"SHA fetch network error: {exc}") from exc

        if response.status_code == status.HTTP_200_OK:
            return response.json().get("sha")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            logger.info(
                "GitHub Pages: file %s does not yet exist in %s — first publish",
                self._file_path,
                self._repo,
            )
            return None
        if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise _TransientError(f"SHA fetch 5xx: {response.status_code} {response.text}")
        raise GitHubPagesError(
            f"GitHub Pages SHA fetch failed fast with HTTP {response.status_code}: {response.text}"
        )

    def _put_content(self, content_b64: str, commit_message: str, sha: str | None) -> str:
        """Commit the encoded file content and return the commit HTML URL.

        Raises:
            GitHubPagesError: On fail-fast 4xx responses other than 409.
            _ConflictError: On 409 Conflict — caller refetches the SHA
                and retries.
            _TransientError: On 5xx or network errors.
        """
        payload: dict = {
            "message": commit_message,
            "content": content_b64,
            "branch": self._branch,
            "author": {"name": self._author_name, "email": self._author_email},
            "committer": {"name": self._author_name, "email": self._author_email},
        }
        if sha is not None:
            payload["sha"] = sha

        try:
            with httpx.Client(timeout=settings.http_request_timeout) as client:
                response = client.put(self._contents_url, headers=self._headers, json=payload)
        except httpx.HTTPError as exc:
            raise _TransientError(f"PUT network error: {exc}") from exc

        if response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED):
            commit_url = response.json().get("commit", {}).get("html_url", "")
            if not commit_url:
                raise GitHubPagesError(
                    "GitHub Pages PUT succeeded but response did not include commit.html_url"
                )
            return commit_url
        if response.status_code == status.HTTP_409_CONFLICT:
            raise _ConflictError(response.text)
        if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise _TransientError(f"PUT 5xx: {response.status_code} {response.text}")
        raise GitHubPagesError(
            f"GitHub Pages PUT failed fast with HTTP {response.status_code}: {response.text}"
        )


class _ConflictError(Exception):
    """Internal sentinel — raised on 409 Conflict so the caller retries the GET/PUT cycle."""


class _TransientError(Exception):
    """Internal sentinel — raised on retryable transport or 5xx failures."""
