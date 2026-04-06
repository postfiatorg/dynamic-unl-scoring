"""Tests for the IPFS pinning client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from scoring_service.clients.ipfs import IPFSClient, _parse_directory_response


SINGLE_FILE_RESPONSE = '{"Name":"test.json","Hash":"QmSingleFileHash","Size":"42"}'

DIRECTORY_RESPONSE = "\n".join([
    '{"Name":"metadata.json","Hash":"QmFileHash1","Size":"100"}',
    '{"Name":"raw/vhs_validators.json","Hash":"QmFileHash2","Size":"200"}',
    '{"Name":"","Hash":"QmRootDirectoryCID","Size":"300"}',
])


class TestInit:
    @patch("scoring_service.clients.ipfs.settings")
    def test_raises_when_api_url_missing(self, mock_settings):
        mock_settings.ipfs_api_url = ""
        with pytest.raises(ValueError, match="IPFS_API_URL is required"):
            IPFSClient()

    @patch("scoring_service.clients.ipfs.settings")
    def test_uses_explicit_url(self, mock_settings):
        mock_settings.ipfs_api_url = "https://default.example.com"
        mock_settings.ipfs_api_username = ""
        mock_settings.ipfs_api_password = ""
        client = IPFSClient(api_url="https://custom.example.com")
        assert client.api_url == "https://custom.example.com"

    @patch("scoring_service.clients.ipfs.settings")
    def test_uses_settings_url(self, mock_settings):
        mock_settings.ipfs_api_url = "https://from-settings.example.com"
        mock_settings.ipfs_api_username = ""
        mock_settings.ipfs_api_password = ""
        client = IPFSClient()
        assert client.api_url == "https://from-settings.example.com"

    @patch("scoring_service.clients.ipfs.settings")
    def test_strips_trailing_slash(self, mock_settings):
        mock_settings.ipfs_api_url = "https://example.com/"
        mock_settings.ipfs_api_username = ""
        mock_settings.ipfs_api_password = ""
        client = IPFSClient()
        assert client.api_url == "https://example.com"

    @patch("scoring_service.clients.ipfs.settings")
    def test_sets_auth_when_credentials_provided(self, mock_settings):
        mock_settings.ipfs_api_url = "https://example.com"
        mock_settings.ipfs_api_username = "admin"
        mock_settings.ipfs_api_password = "secret"
        client = IPFSClient()
        assert client._auth is not None

    @patch("scoring_service.clients.ipfs.settings")
    def test_no_auth_when_credentials_missing(self, mock_settings):
        mock_settings.ipfs_api_url = "https://example.com"
        mock_settings.ipfs_api_username = ""
        mock_settings.ipfs_api_password = ""
        client = IPFSClient()
        assert client._auth is None

    @patch("scoring_service.clients.ipfs.settings")
    def test_explicit_credentials_override_settings(self, mock_settings):
        mock_settings.ipfs_api_url = "https://example.com"
        mock_settings.ipfs_api_username = "default_user"
        mock_settings.ipfs_api_password = "default_pass"
        client = IPFSClient(username="custom_user", password="custom_pass")
        assert client._auth is not None


@pytest.fixture
def client():
    with patch("scoring_service.clients.ipfs.settings") as mock_settings:
        mock_settings.ipfs_api_url = "https://ipfs.test.example.com"
        mock_settings.ipfs_api_username = "admin"
        mock_settings.ipfs_api_password = "secret"
        mock_settings.http_request_timeout = 30
        mock_settings.http_max_retries = 3
        mock_settings.http_retry_base_delay = 2
        yield IPFSClient()


class TestPinFile:
    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_returns_cid_on_success(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Name": "test.json", "Hash": "QmTestCID", "Size": "42"}
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_file("test.json", b'{"key": "value"}')
        assert result == "QmTestCID"

    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_returns_none_when_hash_missing(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Name": "test.json", "Size": "42"}
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_file("test.json", b'data')
        assert result is None

    @patch("scoring_service.clients.ipfs.httpx.Client")
    @patch("scoring_service.clients.ipfs.time.sleep")
    def test_retries_on_http_error(self, mock_sleep, mock_client_cls, client):
        mock_success_response = MagicMock()
        mock_success_response.json.return_value = {"Name": "test.json", "Hash": "QmTestCID", "Size": "42"}
        mock_success_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = [
            httpx.ConnectError("connection refused"),
            mock_success_response,
        ]
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_file("test.json", b'data')
        assert result == "QmTestCID"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.ipfs.httpx.Client")
    @patch("scoring_service.clients.ipfs.time.sleep")
    def test_returns_none_after_retries_exhausted(self, mock_sleep, mock_client_cls, client):
        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_file("test.json", b'data')
        assert result is None
        assert mock_sleep.call_count == 2

    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_posts_to_correct_url(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Name": "test.json", "Hash": "QmTestCID", "Size": "42"}
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_file("test.json", b'data')

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://ipfs.test.example.com/api/v0/add"


class TestPinDirectory:
    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_returns_root_cid_on_success(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.text = DIRECTORY_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        files = {
            "metadata.json": b'{"round": 1}',
            "raw/vhs_validators.json": b'[{"key": "val"}]',
        }
        result = client.pin_directory(files)
        assert result == "QmRootDirectoryCID"

    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_returns_none_for_empty_files(self, mock_client_cls, client):
        result = client.pin_directory({})
        assert result is None
        mock_client_cls.assert_not_called()

    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_returns_none_when_root_cid_missing(self, mock_client_cls, client):
        response_without_root = '{"Name":"file.json","Hash":"QmFileHash","Size":"100"}'
        mock_response = MagicMock()
        mock_response.text = response_without_root
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_directory({"file.json": b'data'})
        assert result is None

    @patch("scoring_service.clients.ipfs.httpx.Client")
    @patch("scoring_service.clients.ipfs.time.sleep")
    def test_retries_on_http_error(self, mock_sleep, mock_client_cls, client):
        mock_success_response = MagicMock()
        mock_success_response.text = DIRECTORY_RESPONSE
        mock_success_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = [
            httpx.TimeoutException("request timed out"),
            mock_success_response,
        ]
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_directory({"file.json": b'data'})
        assert result == "QmRootDirectoryCID"
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.ipfs.httpx.Client")
    @patch("scoring_service.clients.ipfs.time.sleep")
    def test_returns_none_after_retries_exhausted(self, mock_sleep, mock_client_cls, client):
        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_directory({"file.json": b'data'})
        assert result is None
        assert mock_sleep.call_count == 2

    @patch("scoring_service.clients.ipfs.httpx.Client")
    def test_posts_to_correct_url_with_wrap_param(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.text = DIRECTORY_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_directory({"file.json": b'data'})

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://ipfs.test.example.com/api/v0/add?wrap-with-directory=true"


class TestParseDirectoryResponse:
    def test_extracts_root_cid(self):
        result = _parse_directory_response(DIRECTORY_RESPONSE)
        assert result == "QmRootDirectoryCID"

    def test_returns_none_when_no_empty_name(self):
        body = '{"Name":"file.json","Hash":"QmHash","Size":"100"}'
        result = _parse_directory_response(body)
        assert result is None

    def test_handles_empty_body(self):
        result = _parse_directory_response("")
        assert result is None

    def test_skips_malformed_lines(self):
        body = "\n".join([
            "not valid json",
            '{"Name":"","Hash":"QmRootCID","Size":"100"}',
        ])
        result = _parse_directory_response(body)
        assert result == "QmRootCID"

    def test_handles_trailing_newlines(self):
        body = '{"Name":"file.json","Hash":"QmHash1","Size":"50"}\n{"Name":"","Hash":"QmRootCID","Size":"100"}\n\n'
        result = _parse_directory_response(body)
        assert result == "QmRootCID"

    def test_uses_last_empty_name_entry(self):
        body = "\n".join([
            '{"Name":"","Hash":"QmFirst","Size":"50"}',
            '{"Name":"","Hash":"QmSecond","Size":"100"}',
        ])
        result = _parse_directory_response(body)
        assert result == "QmSecond"
