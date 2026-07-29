"""Prompt builder for the LLM scoring pipeline.

Transforms a ScoringSnapshot into the messages list consumed by the
ModalClient. Strips cryptographic keys and raw IPs, assigns anonymous
validator IDs, and returns the reverse mapping for score remapping.
"""

import json
import logging
from pathlib import Path

from openai.types.chat import ChatCompletionMessageParam

from scoring_service.config import REPO_ROOT, settings
from scoring_service.models import ScoringSnapshot
from scoring_service.services.provider_families import compute_concentration, family_for

logger = logging.getLogger(__name__)

PROMPT_PATH = REPO_ROOT / "prompts" / "scoring_v9.txt"
SYSTEM_MARKER = "### SYSTEM PROMPT ###"
USER_MARKER = "### USER PROMPT ###"
STRIPPED_FIELDS = {"master_key", "signing_key", "ip"}
# Evidence the model must not see: current UNL membership stays in the frozen
# evidence for audit, but rendering it measurably biased the reliability
# sub-score toward incumbents, and selection continuity is already owned by
# the deterministic churn control.
MODEL_HIDDEN_FIELDS = {"unl"}
CONCENTRATION_PLACEHOLDER = "{network_concentration}"
PROVIDER_FAMILY_FIELD = "provider_family"
MAX_PROMPT_TOKENS_ESTIMATE = 28000
ValidatorIdentityMap = dict[str, dict[str, str]]


class PromptBuilder:
    """Builds scoring prompt messages from a ScoringSnapshot."""

    def __init__(
        self,
        prompt_path: Path | None = None,
        hidden_fields: set[str] | None = None,
    ):
        path = prompt_path or PROMPT_PATH
        raw = path.read_text()
        parts = raw.split(USER_MARKER)
        if len(parts) != 2:
            raise ValueError(
                f"Prompt template must contain exactly one '{USER_MARKER}' marker"
            )

        self._system_prompt = parts[0].replace(SYSTEM_MARKER, "").strip()
        self._user_template = parts[1].strip()
        self._hidden_fields = (
            hidden_fields if hidden_fields is not None else MODEL_HIDDEN_FIELDS
        )
        self._renders_concentration = CONCENTRATION_PLACEHOLDER in self._user_template
        logger.info("Prompt template loaded from %s", path)

    def build(
        self, snapshot: ScoringSnapshot
    ) -> tuple[list[ChatCompletionMessageParam], ValidatorIdentityMap]:
        """Build messages and ID mapping from a snapshot.

        Returns:
            (messages, validator_id_map) where messages is the OpenAI-compatible
            messages list and validator_id_map maps anonymous IDs to validator
            identity fields used to reconcile model output with real validators.
        """
        sorted_validators = sorted(
            snapshot.validators, key=lambda v: v.master_key
        )

        prompt_entries = []
        validator_id_map: ValidatorIdentityMap = {}

        for index, validator in enumerate(sorted_validators, start=1):
            validator_id = f"v{index:03d}"
            validator_id_map[validator_id] = {
                "master_key": validator.master_key,
                "signing_key": validator.signing_key,
            }

            entry = {"validator_id": validator_id}
            data = validator.model_dump(mode="json")
            excluded = STRIPPED_FIELDS | self._hidden_fields
            for key, value in data.items():
                if key not in excluded:
                    entry[key] = value
            if self._renders_concentration:
                entry[PROVIDER_FAMILY_FIELD] = family_for(
                    validator.asn.as_name if validator.asn else None
                )

            prompt_entries.append(entry)

        validator_json = json.dumps(
            prompt_entries, ensure_ascii=False, separators=(",", ":")
        )
        user_content = self._user_template.replace(
            "{validator_data}", validator_json
        )
        if self._renders_concentration:
            concentration_json = json.dumps(
                compute_concentration(sorted_validators),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            user_content = user_content.replace(
                CONCENTRATION_PLACEHOLDER, concentration_json, 1
            )
        user_content = user_content.replace(
            "{unl_max_size}", str(settings.unl_max_size)
        )
        user_content = user_content.replace(
            "{unl_score_cutoff}", str(settings.unl_score_cutoff)
        )
        user_content = user_content.replace(
            "{unl_min_score_gap}", str(settings.unl_min_score_gap)
        )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        token_estimate = sum(len(str(m.get("content", ""))) for m in messages) // 4
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
