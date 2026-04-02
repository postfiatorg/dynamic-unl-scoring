"""Response parser for LLM scoring output.

Extracts JSON from raw LLM text, validates against the expected scoring
contract, and remaps anonymous validator IDs to master keys. The raw
response text is preserved separately for archival.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DIMENSIONAL_FIELDS = ["consensus", "reliability", "software", "diversity", "identity"]
NETWORK_SUMMARY_KEY = "network_summary"


class ValidatorScore(BaseModel):
    """Parsed and validated score for a single validator."""

    master_key: str
    score: int
    consensus: int
    reliability: int
    software: int
    diversity: int
    identity: int
    reasoning: str


class ScoringResult(BaseModel):
    """Complete parsed scoring result from the LLM."""

    validator_scores: list[ValidatorScore]
    network_summary: str
    raw_response: str
    complete: bool
    errors: list[str]


def _extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from raw LLM text, handling common artifacts."""
    cleaned = text.strip()
    if not cleaned:
        return None

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    return None


def _normalize_score(value: object) -> Optional[int]:
    """Normalize a score value to an integer in 0-100, or None if invalid."""
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        score = value
    elif isinstance(value, float) and value.is_integer():
        score = int(value)
    else:
        return None

    return score if 0 <= score <= 100 else None


def parse_response(
    raw_text: str,
    validator_id_map: dict[str, str],
) -> ScoringResult:
    """Parse and validate raw LLM response text into a ScoringResult.

    Args:
        raw_text: Raw text content from the ModalClient.
        validator_id_map: Mapping of anonymous IDs to master keys (from PromptBuilder).

    Returns:
        ScoringResult with validated scores, or an incomplete result with error details.
    """
    errors: list[str] = []

    parsed = _extract_json(raw_text)
    if parsed is None:
        return ScoringResult(
            validator_scores=[],
            network_summary="",
            raw_response=raw_text,
            complete=False,
            errors=["Failed to extract valid JSON from response"],
        )

    network_summary = ""
    if NETWORK_SUMMARY_KEY in parsed:
        summary_value = parsed.pop(NETWORK_SUMMARY_KEY)
        if isinstance(summary_value, str) and summary_value.strip():
            network_summary = summary_value.strip()
        else:
            errors.append("network_summary is missing or empty")
    else:
        errors.append("network_summary field not found in response")

    expected_ids = set(validator_id_map.keys())
    actual_ids = set(parsed.keys())

    missing_ids = sorted(expected_ids - actual_ids)
    extra_ids = sorted(actual_ids - expected_ids)

    if missing_ids:
        errors.append(f"Missing validators: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"Unexpected entries: {', '.join(extra_ids)}")

    validator_scores: list[ValidatorScore] = []

    for validator_id in sorted(expected_ids & actual_ids):
        entry = parsed[validator_id]
        master_key = validator_id_map[validator_id]

        if not isinstance(entry, dict):
            errors.append(f"{validator_id}: entry is not a dict")
            continue

        overall = _normalize_score(entry.get("score"))
        if overall is None:
            errors.append(f"{validator_id}: invalid or missing score")
            continue

        dimensional: dict[str, int] = {}
        dimensional_valid = True
        for field in DIMENSIONAL_FIELDS:
            sub = _normalize_score(entry.get(field))
            if sub is None:
                errors.append(f"{validator_id}: invalid or missing {field} sub-score")
                dimensional_valid = False
            else:
                dimensional[field] = sub

        if not dimensional_valid:
            continue

        reasoning = entry.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            errors.append(f"{validator_id}: missing or empty reasoning")
            continue

        validator_scores.append(
            ValidatorScore(
                master_key=master_key,
                score=overall,
                consensus=dimensional["consensus"],
                reliability=dimensional["reliability"],
                software=dimensional["software"],
                diversity=dimensional["diversity"],
                identity=dimensional["identity"],
                reasoning=reasoning.strip(),
            )
        )

    complete = (
        len(errors) == 0
        and len(validator_scores) == len(expected_ids)
        and bool(network_summary)
    )

    if complete:
        logger.info("Scoring response parsed: %d validators, complete", len(validator_scores))
    else:
        logger.warning(
            "Scoring response parsed with issues: %d/%d validators, %d errors",
            len(validator_scores),
            len(expected_ids),
            len(errors),
        )

    return ScoringResult(
        validator_scores=validator_scores,
        network_summary=network_summary,
        raw_response=raw_text,
        complete=complete,
        errors=errors,
    )
