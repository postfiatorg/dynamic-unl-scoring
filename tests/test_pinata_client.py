"""Tests for the Pinata secondary pinning client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from scoring_service.clients.pinata import PIN_BY_CID_URL, PinataClient


class TestInit:
    @patch("scoring_service.clients.pinata.settings")
    def test_raises_when_credentials_missing(self, mock_settings):
        mock_settings.pinata_api_key = ""
        mock_settings.pinata_api_secret = ""
        with pytest.raises(ValueError, match="PINATA_API_KEY and PINATA_API_SECRET"):
            PinataClient()

    @patch("scoring_service.clients.pinata.settings")
    def test_raises_when_only_key_provided(self, mock_settings):
        mock_settings.pinata_api_key = "key"
        mock_settings.pinata_api_secret = ""
        with pytest.raises(ValueError, match="PINATA_API_KEY and PINATA_API_SECRET"):
            PinataClient()

    @patch("scoring_service.clients.pinata.settings")
    def test_raises_when_only_secret_provided(self, mock_settings):
        mock_settings.pinata_api_key = ""
        mock_settings.pinata_api_secret = "secret"
        with pytest.raises(ValueError, match="PINATA_API_KEY and PINATA_API_SECRET"):
            PinataClient()

    @patch("scoring_service.clients.pinata.settings")
    def test_uses_settings_credentials(self, mock_settings):
        mock_settings.pinata_api_key = "settings_key"
        mock_settings.pinata_api_secret = "settings_secret"
        client = PinataClient()
        assert client._api_key == "settings_key"
        assert client._api_secret == "settings_secret"

    @patch("scoring_service.clients.pinata.settings")
    def test_explicit_credentials_override_settings(self, mock_settings):
        mock_settings.pinata_api_key = "settings_key"
        mock_settings.pinata_api_secret = "settings_secret"
        client = PinataClient(api_key="explicit_key", api_secret="explicit_secret")
        assert client._api_key == "explicit_key"
        assert client._api_secret == "explicit_secret"


@pytest.fixture
def client():
    with patch("scoring_service.clients.pinata.settings") as mock_settings:
        mock_settings.pinata_api_key = "test_key"
        mock_settings.pinata_api_secret = "test_secret"
        mock_settings.http_request_timeout = 30
        mock_settings.http_max_retries = 3
        mock_settings.http_retry_base_delay = 2
        yield PinataClient()


class TestPinByCid:
    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_returns_true_on_success(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_response))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_by_cid("QmTestCID")
        assert result is True

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_returns_false_on_empty_cid(self, mock_client_cls, client):
        result = client.pin_by_cid("")
        assert result is False
        mock_client_cls.assert_not_called()

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_posts_to_pin_by_hash_endpoint(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_by_cid("QmTestCID")

        call_args = mock_post.call_args
        assert call_args[0][0] == PIN_BY_CID_URL
        assert call_args[0][0] == "https://api.pinata.cloud/pinning/pinByHash"

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_sends_cid_in_body(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_by_cid("QmTestCID")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["hashToPin"] == "QmTestCID"

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_includes_name_in_metadata(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_by_cid("QmTestCID", name="round-1")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["pinataMetadata"]["name"] == "round-1"

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_omits_metadata_when_name_not_provided(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_by_cid("QmTestCID")

        payload = mock_post.call_args.kwargs["json"]
        assert "pinataMetadata" not in payload

    @patch("scoring_service.clients.pinata.httpx.Client")
    def test_sends_auth_headers(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        client.pin_by_cid("QmTestCID")

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["pinata_api_key"] == "test_key"
        assert headers["pinata_secret_api_key"] == "test_secret"
        assert headers["Content-Type"] == "application/json"

    @patch("scoring_service.clients.pinata.httpx.Client")
    @patch("scoring_service.clients.pinata.time.sleep")
    def test_retries_on_http_error(self, mock_sleep, mock_client_cls, client):
        mock_success_response = MagicMock()
        mock_success_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = [
            httpx.ConnectError("connection refused"),
            mock_success_response,
        ]
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_by_cid("QmTestCID")
        assert result is True
        mock_sleep.assert_called_once_with(2)

    @patch("scoring_service.clients.pinata.httpx.Client")
    @patch("scoring_service.clients.pinata.time.sleep")
    def test_returns_false_after_retries_exhausted(self, mock_sleep, mock_client_cls, client):
        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_by_cid("QmTestCID")
        assert result is False
        assert mock_sleep.call_count == 2

    @patch("scoring_service.clients.pinata.httpx.Client")
    @patch("scoring_service.clients.pinata.time.sleep")
    def test_returns_false_on_http_status_error(self, mock_sleep, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = client.pin_by_cid("QmTestCID")
        assert result is False
