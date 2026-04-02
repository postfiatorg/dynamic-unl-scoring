"""Tests for the ModalClient LLM scoring client."""

from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError, APITimeoutError

from scoring_service.clients.modal import ModalClient


SAMPLE_MESSAGES = [
    {"role": "system", "content": "You are a scoring assistant."},
    {"role": "user", "content": "Score these validators."},
]

SAMPLE_RESPONSE_TEXT = '{"v001": {"score": 85, "reasoning": "Good uptime."}}'


def _mock_response(content=SAMPLE_RESPONSE_TEXT):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_empty_response():
    response = MagicMock()
    response.choices = []
    return response


class TestInit:
    @patch("scoring_service.clients.modal.settings")
    def test_raises_when_endpoint_url_missing(self, mock_settings):
        mock_settings.modal_endpoint_url = ""
        with pytest.raises(ValueError, match="MODAL_ENDPOINT_URL is required"):
            ModalClient()

    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_creates_client_with_configured_url(self, mock_openai, mock_settings):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"
        ModalClient()
        mock_openai.assert_called_once_with(
            base_url="https://example.modal.run/v1",
            api_key="not-needed",
            timeout=1800,
        )

    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_does_not_double_append_v1(self, mock_openai, mock_settings):
        mock_settings.modal_endpoint_url = "https://example.modal.run/v1"
        mock_settings.scoring_model_id = "test-model"
        ModalClient()
        mock_openai.assert_called_once_with(
            base_url="https://example.modal.run/v1",
            api_key="not-needed",
            timeout=1800,
        )

    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_explicit_url_overrides_settings(self, mock_openai, mock_settings):
        mock_settings.modal_endpoint_url = "https://default.modal.run"
        mock_settings.scoring_model_id = "test-model"
        ModalClient(endpoint_url="https://custom.modal.run")
        mock_openai.assert_called_once_with(
            base_url="https://custom.modal.run/v1",
            api_key="not-needed",
            timeout=1800,
        )


class TestScore:
    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_returns_response_content(self, mock_openai, mock_settings):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response()
        mock_openai.return_value = mock_client

        client = ModalClient()
        result = client.score(SAMPLE_MESSAGES)

        assert result == SAMPLE_RESPONSE_TEXT
        mock_client.chat.completions.create.assert_called_once_with(
            model="test-model",
            messages=SAMPLE_MESSAGES,
            temperature=0,
            max_tokens=16384,
            response_format={"type": "json_object"},
        )

    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_returns_none_on_empty_choices(self, mock_openai, mock_settings):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_empty_response()
        mock_openai.return_value = mock_client

        client = ModalClient()
        result = client.score(SAMPLE_MESSAGES)
        assert result is None

    @patch("scoring_service.clients.modal.time")
    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_retries_on_timeout_then_succeeds(self, mock_openai, mock_settings, mock_time):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"
        mock_time.time.return_value = 0

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            APITimeoutError(request=MagicMock()),
            _mock_response(),
        ]
        mock_openai.return_value = mock_client

        client = ModalClient()
        result = client.score(SAMPLE_MESSAGES)

        assert result == SAMPLE_RESPONSE_TEXT
        assert mock_client.chat.completions.create.call_count == 2
        mock_time.sleep.assert_called_once_with(5)

    @patch("scoring_service.clients.modal.time")
    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_retries_on_connection_error_then_succeeds(self, mock_openai, mock_settings, mock_time):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"
        mock_time.time.return_value = 0

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            APIConnectionError(request=MagicMock()),
            _mock_response(),
        ]
        mock_openai.return_value = mock_client

        client = ModalClient()
        result = client.score(SAMPLE_MESSAGES)

        assert result == SAMPLE_RESPONSE_TEXT
        assert mock_client.chat.completions.create.call_count == 2

    @patch("scoring_service.clients.modal.time")
    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_returns_none_after_all_retries_exhausted(self, mock_openai, mock_settings, mock_time):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"
        mock_time.time.return_value = 0

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )
        mock_openai.return_value = mock_client

        client = ModalClient()
        result = client.score(SAMPLE_MESSAGES)

        assert result is None
        assert mock_client.chat.completions.create.call_count == 2

    @patch("scoring_service.clients.modal.time")
    @patch("scoring_service.clients.modal.settings")
    @patch("scoring_service.clients.modal.OpenAI")
    def test_retry_delay_increases_with_attempt(self, mock_openai, mock_settings, mock_time):
        mock_settings.modal_endpoint_url = "https://example.modal.run"
        mock_settings.scoring_model_id = "test-model"
        mock_time.time.return_value = 0

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APIConnectionError(
            request=MagicMock()
        )
        mock_openai.return_value = mock_client

        client = ModalClient()
        client.score(SAMPLE_MESSAGES)

        mock_time.sleep.assert_called_once_with(5)
