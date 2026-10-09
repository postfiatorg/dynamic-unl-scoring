"""Deterministic diversity sub-score (diversity formula v1).

Computes the authoritative per-validator diversity sub-score from the two
concentration counts the collector already produces and the model already
receives: how many validators in the round share the validator's country
and how many share its provider family. The model's own diversity value
stays in the published output as advisory; this module owns the number the
score formula consumes. Integer arithmetic only, so any independent
reimplementation is bit-identical. Specification, rationale, and empirical
validation live in docs/DeterministicDiversity.md.

The counts come from the frozen ``inputs/diversity_inputs.json`` so the
service and every sidecar compute from the same bytes.

This module is content-hash-pinned in every round's execution manifest
(``code.diversity_formula``), like the response parser, the UNL selector,
and the score formula.
"""

from scoring_service.services.response_parser import ScoringResult

DIVERSITY_FORMULA_VERSION = 1

# Each axis (country, provider family) is worth half of the 100 points.
AXIS_POINTS = 50

# Points an axis loses when every other resolved validator shares it; a
# value above AXIS_POINTS means the axis bottoms out before full crowding.
# Calibrated so the formula's mean over testnet rounds 23-26 equals the
# model's mean; see the design doc.
AXIS_PENALTY = 119

# An axis whose value is unknown cannot show how crowded it is; it gets a
# fixed fraction of its points, half of what a fully unknown validator
# received from the model in production.
UNKNOWN_AXIS_POINTS = 10


def _axis_numerator(sharing_validators: int | None, others: int) -> int:
    """Points for one axis, scaled by ``others`` to stay in integers."""
    if sharing_validators is None:
        return UNKNOWN_AXIS_POINTS * others
    return max(0, AXIS_POINTS * others - AXIS_PENALTY * (sharing_validators - 1))


def compute_diversity(
    country_validators: int | None,
    provider_validators: int | None,
    resolved_endpoints: int,
) -> int:
    """Compute one validator's diversity sub-score.

    ``country_validators`` and ``provider_validators`` count the validators
    in the round sharing the axis value, the validator itself included;
    ``None`` means the axis is unknown. ``resolved_endpoints`` is the number
    of validators with a known provider family, the concentration block's
    total minus its unresolved count, and scales both axes.
    """
    others = resolved_endpoints - 1
    if others < 1:
        # A lone resolved validator shares nothing; an unknown axis keeps
        # its fixed points.
        return sum(
            UNKNOWN_AXIS_POINTS if value is None else AXIS_POINTS
            for value in (country_validators, provider_validators)
        )
    numerator = _axis_numerator(country_validators, others) + _axis_numerator(
        provider_validators, others
    )
    # Round half up without floating point.
    return (2 * numerator + others) // (2 * others)


def apply_diversity_formula(
    scoring_result: ScoringResult, diversity_inputs: dict
) -> ScoringResult:
    """Return a copy of the result whose diversity sub-scores are computed.

    The input result keeps the model's advisory diversity untouched — it is
    what the artifacts publish as pure model output. The returned copy is
    what the score formula and UNL selection consume. A validator without
    an inputs entry fails the round rather than keeping the advisory value.
    """
    inputs = {entry["master_key"]: entry for entry in diversity_inputs["validators"]}
    missing = [
        v.master_key for v in scoring_result.validator_scores if v.master_key not in inputs
    ]
    if missing:
        raise ValueError(f"diversity inputs carry no entry for {missing}")
    resolved_endpoints = diversity_inputs["resolved_endpoints"]
    return scoring_result.model_copy(
        update={
            "validator_scores": [
                v.model_copy(
                    update={
                        "diversity": compute_diversity(
                            inputs[v.master_key]["country_validators"],
                            inputs[v.master_key]["provider_validators"],
                            resolved_endpoints,
                        )
                    }
                )
                for v in scoring_result.validator_scores
            ]
        }
    )


def diversity_formula_parameters() -> dict:
    """The parameters recorded in the execution manifest and the artifacts."""
    return {
        "axis_points": AXIS_POINTS,
        "axis_penalty": AXIS_PENALTY,
        "unknown_axis_points": UNKNOWN_AXIS_POINTS,
    }
