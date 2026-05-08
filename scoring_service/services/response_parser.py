"""Response parser for LLM scoring output.

Extracts JSON from raw LLM text, validates against the expected scoring
contract, and remaps anonymous validator IDs to master keys. The raw
response text is preserved separately for archival.
"""

import json
import logging
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from scoring_service.services.prompt_builder import ValidatorIdentityMap

logger = logging.getLogger(__name__)

DIMENSIONAL_FIELDS = ["consensus", "reliability", "software", "diversity", "identity"]
NETWORK_SUMMARY_KEY = "network_summary"
NETWORK_REPORT_KEY = "network_report"
NETWORK_REPORT_CATEGORIES = tuple(DIMENSIONAL_FIELDS)
NetworkReportTone = Literal["positive", "mixed", "warning", "negative", "neutral"]


class NetworkReportCategory(BaseModel):
    """Structured round-level reasoning for one scoring dimension."""

    tone: NetworkReportTone
    body: str

    @field_validator("body")
    @classmethod
    def _body_must_be_present(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must be a non-empty string")
        return stripped


class NetworkReport(BaseModel):
    """Structured round-level scoring report."""

    headline: str
    summary: str
    categories: dict[str, NetworkReportCategory]

    @field_validator("headline", "summary")
    @classmethod
    def _text_must_be_present(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be a non-empty string")
        return stripped

    @model_validator(mode="after")
    def _categories_must_match_scoring_dimensions(self) -> "NetworkReport":
        actual = set(self.categories)
        expected = set(NETWORK_REPORT_CATEGORIES)

        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"missing categories: {', '.join(missing)}")
            if extra:
                parts.append(f"unexpected categories: {', '.join(extra)}")
            raise ValueError("; ".join(parts))

        return self


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
    network_summary: str = ""
    network_report: Optional[NetworkReport] = None
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


def _format_validation_errors(exc: ValidationError) -> str:
    formatted = []
    for issue in exc.errors(
        include_context=False,
        include_input=False,
        include_url=False,
    ):
        location = ".".join(str(part) for part in issue.get("loc", ()))
        message = issue.get("msg", "invalid value")
        formatted.append(f"{location}: {message}" if location else message)

    return "; ".join(formatted)


def parse_response(
    raw_text: str,
    validator_id_map: ValidatorIdentityMap,
) -> ScoringResult:
    """Parse and validate raw LLM response text into a ScoringResult.

    Args:
        raw_text: Raw text content from the ModalClient.
        validator_id_map: Mapping of anonymous IDs to validator identities
            (from PromptBuilder).

    Returns:
        ScoringResult with validated scores, or an incomplete result with error details.
    """
    errors: list[str] = []

    parsed = _extract_json(raw_text)
    if parsed is None:
        return ScoringResult(
            validator_scores=[],
            network_summary="",
            network_report=None,
            raw_response=raw_text,
            complete=False,
            errors=["Failed to extract valid JSON from response"],
        )

    has_network_summary = NETWORK_SUMMARY_KEY in parsed
    has_network_report = NETWORK_REPORT_KEY in parsed

    network_summary = ""
    if has_network_summary:
        summary_value = parsed.pop(NETWORK_SUMMARY_KEY)
        if isinstance(summary_value, str) and summary_value.strip():
            network_summary = summary_value.strip()
        else:
            errors.append("network_summary is missing or empty")

    network_report: Optional[NetworkReport] = None
    if has_network_report:
        report_value = parsed.pop(NETWORK_REPORT_KEY)
        try:
            network_report = NetworkReport.model_validate(report_value)
        except ValidationError as exc:
            errors.append(f"network_report is invalid: {_format_validation_errors(exc)}")

    if not has_network_summary and not has_network_report:
        errors.append("network_summary or network_report field not found in response")

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
        master_key = validator_id_map[validator_id]["master_key"]

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
        and (bool(network_summary) or network_report is not None)
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
        network_report=network_report,
        raw_response=raw_text,
        complete=complete,
        errors=errors,
    )
