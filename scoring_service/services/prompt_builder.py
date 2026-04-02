"""Prompt builder for the LLM scoring pipeline.

Transforms a ScoringSnapshot into the messages list consumed by the
ModalClient. Strips cryptographic keys and raw IPs, assigns anonymous
validator IDs, and returns the reverse mapping for score remapping.
"""

import json
import logging
from pathlib import Path

from scoring_service.config import REPO_ROOT
from scoring_service.models import ScoringSnapshot

logger = logging.getLogger(__name__)

PROMPT_PATH = REPO_ROOT / "prompts" / "scoring_v2.txt"
SYSTEM_MARKER = "### SYSTEM PROMPT ###"
USER_MARKER = "### USER PROMPT ###"
STRIPPED_FIELDS = {"master_key", "signing_key", "ip"}
MAX_PROMPT_TOKENS_ESTIMATE = 28000


class PromptBuilder:
    """Builds scoring prompt messages from a ScoringSnapshot."""

    def __init__(self, prompt_path: Path | None = None):
        path = prompt_path or PROMPT_PATH
        raw = path.read_text()
        parts = raw.split(USER_MARKER)
        if len(parts) != 2:
            raise ValueError(
                f"Prompt template must contain exactly one '{USER_MARKER}' marker"
            )

        self._system_prompt = parts[0].replace(SYSTEM_MARKER, "").strip()
        self._user_template = parts[1].strip()
        logger.info("Prompt template loaded from %s", path)

    def build(
        self, snapshot: ScoringSnapshot
    ) -> tuple[list[dict], dict[str, str]]:
        """Build messages and ID mapping from a snapshot.

        Returns:
            (messages, validator_id_map) where messages is the OpenAI-compatible
            messages list and validator_id_map maps anonymous IDs to master keys.
        """
        sorted_validators = sorted(
            snapshot.validators, key=lambda v: v.master_key
        )

        prompt_entries = []
        validator_id_map: dict[str, str] = {}

        for index, validator in enumerate(sorted_validators, start=1):
            validator_id = f"v{index:03d}"
            validator_id_map[validator_id] = validator.master_key

            entry = {"validator_id": validator_id}
            data = validator.model_dump(mode="json")
            for key, value in data.items():
                if key not in STRIPPED_FIELDS:
                    entry[key] = value

            prompt_entries.append(entry)

        validator_json = json.dumps(
            prompt_entries, ensure_ascii=False, separators=(",", ":")
        )
        user_content = self._user_template.replace(
            "{validator_data}", validator_json
        )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        token_estimate = sum(len(m["content"]) for m in messages) // 4
        if token_estimate > MAX_PROMPT_TOKENS_ESTIMATE:
            logger.warning(
                "Prompt token estimate (%d) exceeds budget (%d)",
                token_estimate,
                MAX_PROMPT_TOKENS_ESTIMATE,
            )

        logger.info(
            "Prompt built: %d validators, ~%d tokens",
            len(sorted_validators),
            token_estimate,
        )
        return messages, validator_id_map
