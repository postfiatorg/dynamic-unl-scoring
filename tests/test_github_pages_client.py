"""Tests for the GitHub Pages client that distributes signed VLs."""

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import status

from scoring_service.clients.github_pages import (
    GITHUB_API_BASE,
    GitHubPagesClient,
    GitHubPagesError,
)


class TestInit:
    @patch("scoring_service.clients.github_pages.settings")
    def test_raises_when_token_missing(self, mock_settings):
        mock_settings.github_pages_token = ""
        mock_settings.github_pages_repo = "owner/repo"
        mock_settings.github_pages_file_path = "vl.json"
        mock_settings.github_pages_branch = "main"
        mock_settings.github_pages_commit_author_name = "Bot"
        mock_settings.github_pages_commit_author_email = "bot@example.com"
        with pytest.raises(ValueError, match="GITHUB_PAGES_TOKEN"):
            GitHubPagesClient()

    @patch("scoring_service.clients.github_pages.settings")
    def test_raises_when_repo_missing(self, mock_settings):
        mock_settings.github_pages_token = "t"
        mock_settings.github_pages_repo = ""
        mock_settings.github_pages_file_path = "vl.json"
        mock_settings.github_pages_branch = "main"
        mock_settings.github_pages_commit_author_name = "Bot"
        mock_settings.github_pages_commit_author_email = "bot@example.com"
        with pytest.raises(ValueError, match="GITHUB_PAGES_REPO"):
            GitHubPagesClient()

    @patch("scoring_service.clients.github_pages.settings")
    def test_raises_when_file_path_missing(self, mock_settings):
        mock_settings.github_pages_token = "t"
        mock_settings.github_pages_repo = "owner/repo"
        mock_settings.github_pages_file_path = ""
        mock_settings.github_pages_branch = "main"
        mock_settings.github_pages_commit_author_name = "Bot"
        mock_settings.github_pages_commit_author_email = "bot@example.com"
        with pytest.raises(ValueError, match="GITHUB_PAGES_FILE_PATH"):
            GitHubPagesClient()

    @patch("scoring_service.clients.github_pages.settings")
    def test_explicit_overrides_beat_settings(self, mock_settings):
        mock_settings.github_pages_token = "env_token"
        mock_settings.github_pages_repo = "env/repo"
        mock_settings.github_pages_file_path = "env.json"
        mock_settings.github_pages_branch = "dev"
        mock_settings.github_pages_commit_author_name = "Env"
        mock_settings.github_pages_commit_author_email = "env@example.com"

        client = GitHubPagesClient(
            token="explicit_token",
            repo="explicit/repo",
            file_path="explicit.json",
            branch="main",
            commit_author_name="Explicit",
            commit_author_email="explicit@example.com",
        )

        assert client._token == "explicit_token"
        assert client._repo == "explicit/repo"
        assert client._file_path == "explicit.json"
        assert client._branch == "main"
        assert client._author_name == "Explicit"
        assert client._author_email == "explicit@example.com"


@pytest.fixture
def client():
    with patch("scoring_service.clients.github_pages.settings") as mock_settings:
        mock_settings.github_pages_token = "test_token"
        mock_settings.github_pages_repo = "postfiatorg/postfiatorg.github.io"
        mock_settings.github_pages_file_path = "devnet_vl.json"
        mock_settings.github_pages_branch = "main"
        mock_settings.github_pages_commit_author_name = "PostFiat Scoring Service"
        mock_settings.github_pages_commit_author_email = "scoring@postfiat.org"
        mock_settings.http_request_timeout = 30
        mock_settings.http_max_retries = 3
        mock_settings.http_retry_base_delay = 2
        yield GitHubPagesClient()


def _mock_http_client(get_response=None, put_response=None, get_side_effect=None, put_side_effect=None):
    """Build a mocked httpx.Client context manager with GET and PUT stubs."""
    inner = MagicMock()
    if get_side_effect is not None:
        inner.get.side_effect = get_side_effect
    else:
        inner.get.return_value = get_response
    if put_side_effect is not None:
        inner.put.side_effect = put_side_effect
    else:
        inner.put.return_value = put_response
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, inner


def _response(status_code: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    return resp


class TestPublishHappyPath:
    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_fetches_sha_then_puts_content(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc123"})
        put_resp = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://github.com/owner/repo/commit/xyz"}})
        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        url = client.publish(content='{"sequence": 1}', commit_message="Round 1")

        assert url == "https://github.com/owner/repo/commit/xyz"
        assert inner.get.call_count == 1
        assert inner.put.call_count == 1

    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_put_payload_carries_expected_fields(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc123"})
        put_resp = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://github.com/owner/repo/commit/xyz"}})
        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        client.publish(content='{"sequence": 1}', commit_message="Round 1")

        payload = inner.put.call_args.kwargs["json"]
        assert payload["message"] == "Round 1"
        assert payload["branch"] == "main"
        assert payload["sha"] == "abc123"
        assert payload["author"] == {
            "name": "PostFiat Scoring Service",
            "email": "scoring@postfiat.org",
        }
        assert payload["committer"] == payload["author"]
        decoded = base64.b64decode(payload["content"]).decode("utf-8")
        assert decoded == '{"sequence": 1}'

    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_targets_correct_api_url(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        put_resp = _response(status.HTTP_200_OK, {"commit": {"html_url": "x"}})
        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        client.publish(content="{}", commit_message="m")

        expected_url = f"{GITHUB_API_BASE}/repos/postfiatorg/postfiatorg.github.io/contents/devnet_vl.json"
        assert inner.get.call_args.args[0] == expected_url
        assert inner.put.call_args.args[0] == expected_url

    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_sends_auth_and_api_version_headers(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        put_resp = _response(status.HTTP_200_OK, {"commit": {"html_url": "x"}})
        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        client.publish(content="{}", commit_message="m")

        headers = inner.put.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test_token"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestPublishFirstTime:
    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_omits_sha_when_file_does_not_exist(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_404_NOT_FOUND, text="Not Found")
        put_resp = _response(status.HTTP_201_CREATED, {"commit": {"html_url": "https://github.com/owner/repo/commit/new"}})
        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        url = client.publish(content='{"sequence": 1}', commit_message="First publish")

        assert url == "https://github.com/owner/repo/commit/new"
        payload = inner.put.call_args.kwargs["json"]
        assert "sha" not in payload


class TestPublishConflictRetry:
    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_retries_get_and_put_on_409(self, mock_sleep, mock_client_cls, client):
        first_get = _response(status.HTTP_200_OK, {"sha": "sha_v1"})
        conflict = _response(status.HTTP_409_CONFLICT, text="Conflict")
        second_get = _response(status.HTTP_200_OK, {"sha": "sha_v2"})
        success = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://github.com/owner/repo/commit/win"}})

        ctx, inner = _mock_http_client()
        inner.get.side_effect = [first_get, second_get]
        inner.put.side_effect = [conflict, success]
        mock_client_cls.return_value = ctx

        url = client.publish(content='{"x": 1}', commit_message="retry test")

        assert url == "https://github.com/owner/repo/commit/win"
        assert inner.get.call_count == 2
        assert inner.put.call_count == 2
        # The second PUT must carry the refreshed SHA.
        second_payload = inner.put.call_args_list[1].kwargs["json"]
        assert second_payload["sha"] == "sha_v2"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_raises_after_persistent_conflicts(self, mock_sleep, mock_client_cls, client):
        ctx, inner = _mock_http_client()
        inner.get.return_value = _response(status.HTTP_200_OK, {"sha": "sha_any"})
        inner.put.return_value = _response(status.HTTP_409_CONFLICT, text="Conflict")
        mock_client_cls.return_value = ctx

        with pytest.raises(GitHubPagesError, match="persistent SHA conflicts"):
            client.publish(content='{"x": 1}', commit_message="still conflicting")

        # 3 attempts -> 2 sleeps (no sleep after final failure)
        assert mock_sleep.call_count == 2


class TestPublishTransientRetry:
    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_retries_on_5xx_from_put(self, mock_sleep, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        flaky = _response(status.HTTP_502_BAD_GATEWAY, text="Bad Gateway")
        success = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://x/commit/ok"}})

        ctx, inner = _mock_http_client()
        inner.get.return_value = get_resp
        inner.put.side_effect = [flaky, success]
        mock_client_cls.return_value = ctx

        url = client.publish(content="{}", commit_message="flaky")

        assert url == "https://x/commit/ok"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_retries_on_network_error(self, mock_sleep, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        success = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://x/commit/ok"}})

        ctx, inner = _mock_http_client()
        inner.get.return_value = get_resp
        inner.put.side_effect = [httpx.ConnectError("dropped"), success]
        mock_client_cls.return_value = ctx

        url = client.publish(content="{}", commit_message="net flap")

        assert url == "https://x/commit/ok"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_retries_on_5xx_from_get(self, mock_sleep, mock_client_cls, client):
        flaky_get = _response(status.HTTP_503_SERVICE_UNAVAILABLE, text="Service Unavailable")
        ok_get = _response(status.HTTP_200_OK, {"sha": "abc"})
        success = _response(status.HTTP_200_OK, {"commit": {"html_url": "https://x/commit/ok"}})

        ctx, inner = _mock_http_client()
        inner.get.side_effect = [flaky_get, ok_get]
        inner.put.return_value = success
        mock_client_cls.return_value = ctx

        url = client.publish(content="{}", commit_message="flaky get")

        assert url == "https://x/commit/ok"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.github_pages.httpx.Client")
    @patch("scoring_service.clients.github_pages.time.sleep")
    def test_raises_after_persistent_transient_errors(self, mock_sleep, mock_client_cls, client):
        ctx, inner = _mock_http_client()
        inner.get.return_value = _response(status.HTTP_200_OK, {"sha": "abc"})
        inner.put.return_value = _response(status.HTTP_500_INTERNAL_SERVER_ERROR, text="Internal Error")
        mock_client_cls.return_value = ctx

        with pytest.raises(GitHubPagesError, match="transient errors"):
            client.publish(content="{}", commit_message="down")

        assert mock_sleep.call_count == 2


class TestPublishFailFast:
    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_fails_fast_on_put_401(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        put_resp = _response(status.HTTP_401_UNAUTHORIZED, text="Bad credentials")

        ctx, inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        with pytest.raises(GitHubPagesError, match="failed fast with HTTP 401"):
            client.publish(content="{}", commit_message="auth fail")

        assert inner.put.call_count == 1  # no retries

    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_fails_fast_on_get_403(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_403_FORBIDDEN, text="Forbidden")

        ctx, inner = _mock_http_client(get_response=get_resp, put_response=None)
        mock_client_cls.return_value = ctx

        with pytest.raises(GitHubPagesError, match="failed fast with HTTP 403"):
            client.publish(content="{}", commit_message="forbidden")

        assert inner.put.call_count == 0

    @patch("scoring_service.clients.github_pages.httpx.Client")
    def test_raises_when_put_response_missing_commit_url(self, mock_client_cls, client):
        get_resp = _response(status.HTTP_200_OK, {"sha": "abc"})
        put_resp = _response(status.HTTP_200_OK, {"commit": {}})  # no html_url
        ctx, _inner = _mock_http_client(get_response=get_resp, put_response=put_resp)
        mock_client_cls.return_value = ctx

        with pytest.raises(GitHubPagesError, match="html_url"):
            client.publish(content="{}", commit_message="malformed")
