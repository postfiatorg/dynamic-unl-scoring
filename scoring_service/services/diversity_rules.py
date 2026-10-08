"""Deterministic enforcement of the diversity equality and ordering rules.

Scoring prompt v9+ states two crisp rules for the ``diversity`` sub-score
(see ``prompts/scoring_v11.txt``, section 4):

* **Equality** - validators with the same country count and the same
  provider-family count in the NETWORK CONCENTRATION block must receive
  identical diversity sub-scores.
* **Ordering** - a validator no more concentrated than another on either
  axis and strictly less concentrated on at least one must receive a
  strictly higher diversity sub-score.

The model does not always honour them (issue #65: testnet rounds 25 and
26). This module checks the parsed scores against the exact concentration
evidence the model was shown, so a violating response is treated as an
incomplete scoring result by the orchestrator's existing completeness
gate instead of being published.

The check derives every number from the frozen ``model_request`` - the
same NETWORK CONCENTRATION block and ``provider_family`` / ``geolocation``
entry fields rendered by :mod:`scoring_service.services.prompt_builder` -
never from live collector state, so it is reproducible from the published
input package alone. The logic mirrors the ``inconsistent_scores`` and
``ordering_violation`` defects in the governance repository's mechanical
checker so both services agree on what a violation is.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from scoring_service.config import settings
from scoring_service.services.response_parser import (
    ScoringResult,
    ValidatorIdentityMap,
)

logger = logging.getLogger(__name__)

CONCENTRATION_MARKER = "NETWORK CONCENTRATION:"
VALIDATOR_DATA_MARKER = "VALIDATOR DATA:"
UNRESOLVED_FAMILY = "unknown"

ENFORCEMENT_REJECT = "reject"
ENFORCEMENT_WARN = "warn"
ENFORCEMENT_OFF = "off"
ENFORCEMENT_MODES = (ENFORCEMENT_REJECT, ENFORCEMENT_WARN, ENFORCEMENT_OFF)

# A validator already at the ceiling cannot legally score higher, so a tie
# at this value is the cap working rather than an ordering violation.
MAX_SUB_SCORE = 100


@dataclass(frozen=True)
class DiversityEvidence:
    """The two concentration counts the diversity rules compare."""

    validator_id: str
    country_count: int
    family_count: int

    def dominates(self, other: "DiversityEvidence") -> bool:
        """Strictly less concentrated: no axis worse, at least one better."""
        if self.country_count > other.country_count:
            return False
        if self.family_count > other.family_count:
            return False
        return (
            self.country_count < other.country_count
            or self.family_count < other.family_count
        )


class DiversityEvidenceError(ValueError):
    """The request carries a concentration block that cannot be read."""


def _user_content(model_request: dict[str, Any]) -> str | None:
    for message in model_request.get("messages", []) or []:
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else None
    return None


def _decode_after(content: str, marker: str) -> Any | None:
    """The JSON value that follows ``marker`` in ``content``; None if absent."""
    marker_at = content.find(marker)
    if marker_at < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(
            content[marker_at + len(marker) :].lstrip()
        )
    except ValueError as exc:
        raise DiversityEvidenceError(
            f"{marker.rstrip(':')} block is not valid JSON: {exc}"
        ) from exc
    return value


def _count_lookup(block: Any, key_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(block, list):
        raise DiversityEvidenceError(
            f"Concentration block {key_name!r} list is missing or malformed"
        )
    for item in block:
        if (
            not isinstance(item, dict)
            or key_name not in item
            or not isinstance(item.get("validators"), int)
        ):
            raise DiversityEvidenceError(
                f"Concentration block entries must carry {key_name!r} and 'validators'"
            )
        counts[str(item[key_name])] = item["validators"]
    return counts


def _entry_country(entry: dict[str, Any]) -> str | None:
    geolocation = entry.get("geolocation")
    if isinstance(geolocation, dict):
        country = geolocation.get("country")
        return country if isinstance(country, str) and country else None
    country = entry.get("country")
    return country if isinstance(country, str) and country else None


def diversity_evidence(model_request: dict[str, Any]) -> dict[str, DiversityEvidence]:
    """Per-validator concentration counts from the frozen request.

    Returns an empty mapping when the request carries no NETWORK
    CONCENTRATION block (prompt eras before v9), in which case the rules do
    not apply. Validators whose endpoint is unresolved (``provider_family``
    of ``"unknown"`` or no country) are excluded: the missing-endpoint
    policy governs them and they are not comparable under these rules.
    """
    content = _user_content(model_request)
    if content is None:
        return {}
    block = _decode_after(content, CONCENTRATION_MARKER)
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise DiversityEvidenceError("Concentration block must be a JSON object")
    entries = _decode_after(content, VALIDATOR_DATA_MARKER)
    if not isinstance(entries, list):
        raise DiversityEvidenceError(
            "Request carries a concentration block but no validator data list"
        )

    family_counts = _count_lookup(block.get("provider_families", []), "family")
    country_counts = _count_lookup(block.get("countries", []), "country")

    evidence: dict[str, DiversityEvidence] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        validator_id = entry.get("validator_id")
        if not isinstance(validator_id, str):
            continue
        family = entry.get("provider_family")
        country = _entry_country(entry)
        if not family or family == UNRESOLVED_FAMILY or country is None:
            continue
        family_count = family_counts.get(str(family))
        country_count = country_counts.get(country)
        if family_count is None or country_count is None:
            raise DiversityEvidenceError(
                f"{validator_id}: provider family {family!r} or country "
                f"{country!r} is absent from the concentration block"
            )
        evidence[validator_id] = DiversityEvidence(
            validator_id=validator_id,
            country_count=country_count,
            family_count=family_count,
        )
    return evidence


def check_diversity_rules(
    model_request: dict[str, Any],
    scoring_result: ScoringResult,
    validator_id_map: ValidatorIdentityMap,
) -> list[str]:
    """Every equality and ordering violation in the parsed diversity scores.

    Pure and deterministic: the same request, result and identity map
    always yield the same error strings in the same order. An empty list
    means the response honours both rules (or the rules do not apply).
    """
    try:
        evidence = diversity_evidence(model_request)
    except DiversityEvidenceError as exc:
        return [f"diversity rule check could not read the request: {exc}"]
    if not evidence:
        return []

    key_to_id = {
        identity["master_key"]: validator_id
        for validator_id, identity in validator_id_map.items()
        if isinstance(identity, dict) and "master_key" in identity
    }
    scores: dict[str, int] = {}
    for validator_score in scoring_result.validator_scores:
        validator_id = key_to_id.get(validator_score.master_key)
        if validator_id is not None and validator_id in evidence:
            scores[validator_id] = validator_score.diversity
    comparable = sorted(scores)

    errors: list[str] = []

    groups: dict[tuple[int, int], list[str]] = {}
    for validator_id in comparable:
        row = evidence[validator_id]
        groups.setdefault((row.country_count, row.family_count), []).append(
            validator_id
        )
    for (country_count, family_count), members in sorted(groups.items()):
        if len({scores[m] for m in members}) > 1:
            values_text = ", ".join(f"{m}={scores[m]}" for m in members)
            errors.append(
                "diversity equality violation: "
                f"{values_text} share country count {country_count} and "
                f"provider-family count {family_count} but received "
                "different diversity sub-scores"
            )

    for better in comparable:
        for worse in comparable:
            if better == worse or not evidence[better].dominates(evidence[worse]):
                continue
            score_better, score_worse = scores[better], scores[worse]
            if score_better < score_worse or (
                score_better == score_worse and score_better < MAX_SUB_SCORE
            ):
                eb, ew = evidence[better], evidence[worse]
                errors.append(
                    "diversity ordering violation: "
                    f"{better} (country count {eb.country_count}, "
                    f"provider-family count {eb.family_count}) is strictly less "
                    f"concentrated than {worse} (country count {ew.country_count}, "
                    f"provider-family count {ew.family_count}) but scores "
                    f"{score_better} versus {score_worse}"
                )
    return errors


def apply_diversity_rules(
    model_request: dict[str, Any],
    scoring_result: ScoringResult,
    validator_id_map: ValidatorIdentityMap,
    mode: str | None = None,
) -> ScoringResult:
    """Apply the configured enforcement to a parsed scoring result.

    * ``reject`` (default): violations are appended to ``errors`` and the
      result is marked incomplete, so the orchestrator's completeness gate
      fails the round instead of publishing it.
    * ``warn``: violations are logged and the result is returned unchanged.
    * ``off``: the check is skipped.
    """
    mode = mode or settings.diversity_rule_enforcement
    if mode not in ENFORCEMENT_MODES:
        raise ValueError(
            f"diversity_rule_enforcement must be one of {ENFORCEMENT_MODES}, got {mode!r}"
        )
    if mode == ENFORCEMENT_OFF:
        return scoring_result
    errors = check_diversity_rules(model_request, scoring_result, validator_id_map)
    if not errors:
        return scoring_result
    if mode == ENFORCEMENT_WARN:
        for error in errors:
            logger.warning("Diversity rule violation (warn-only): %s", error)
        return scoring_result
    return scoring_result.model_copy(
        update={"complete": False, "errors": [*scoring_result.errors, *errors]}
    )
