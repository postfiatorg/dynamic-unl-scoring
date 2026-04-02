"""Modal LLM client for validator scoring.

Calls the Modal serverless endpoint (Qwen3-Next-80B-A3B-Instruct-FP8 on
SGLang) via its OpenAI-compatible API. Returns raw response text for
downstream parsing by the ScorerService.
"""

import logging
import time
from typing import Optional

from openai import APIConnectionError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject

from scoring_service.config import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 1800
MAX_RETRIES = 2
RETRY_BASE_DELAY = 5
MAX_TOKENS = 16384
JSON_RESPONSE_FORMAT: ResponseFormatJSONObject = {"type": "json_object"}


class ModalClient:
    """Thin client for the Modal SGLang scoring endpoint."""

    def __init__(self, endpoint_url: Optional[str] = None):
        url = endpoint_url or settings.modal_endpoint_url
        if not url:
            raise ValueError(
                "MODAL_ENDPOINT_URL is required but not configured"
            )

        base_url = url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        self._client = OpenAI(
            base_url=base_url,
            api_key="not-needed",
            timeout=REQUEST_TIMEOUT,
        )
        self._model_id = settings.scoring_model_id
        logger.info("Modal client initialized — endpoint: %s", base_url)

    def score(self, messages: list[ChatCompletionMessageParam]) -> Optional[str]:
        """Send scoring messages to the LLM endpoint.

        Returns the raw response text content, or None if all attempts fail.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "Sending scoring request (attempt %d/%d)",
                    attempt,
                    MAX_RETRIES,
                )
                start = time.time()
                response = self._client.chat.completions.create(
                    model=self._model_id,
                    messages=messages,
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                    response_format=JSON_RESPONSE_FORMAT,
                )
                elapsed = time.time() - start
                logger.info("Scoring response received in %.1fs", elapsed)

                choice = response.choices[0] if response.choices else None
                if choice is None:
                    logger.error("Empty response — no choices returned")
                    return None

                return choice.message.content

            except (APITimeoutError, APIConnectionError) as exc:
                if attempt == MAX_RETRIES:
                    logger.error(
                        "Scoring request failed after %d attempts: %s",
                        MAX_RETRIES,
                        exc,
                    )
                    return None
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    "Scoring request attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)

        return None

    def close(self):
        self._client.close()
