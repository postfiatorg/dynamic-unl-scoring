"""Deterministic final-score computation (score formula v1).

Computes the authoritative per-validator final score from the five
dimensional sub-scores, replacing the model's holistic overall score as
the quantity UNL selection consumes. The model's judgment stays in the
sub-scores; this module owns their composition. Integer arithmetic only,
so any independent reimplementation is bit-identical. Specification,
rationale, and empirical validation live in docs/DeterministicFinalScore.md.

This module is content-hash-pinned in every round's execution manifest
(``code.score_formula``), like the response parser and UNL selector.
"""

from scoring_service.services.response_parser import ScoringResult, ValidatorScore

FORMULA_VERSION = 1

WEIGHTS = {
    "consensus": 50,
    "reliability": 20,
    "software": 10,
    "diversity": 10,
    "identity": 10,
}

# Caps the final score at consensus + margin so secondary virtues cannot
# substitute for consensus participation; see the design doc for the
# empirical bound (margin 30 is the first value that lifts a degraded
# validator to the eligibility cutoff).
CONSENSUS_GATE_MARGIN = 25


def compute_final_score(
    consensus: int,
    reliability: int,
    software: int,
    diversity: int,
    identity: int,
) -> int:
    """Compute one validator's final score from its five sub-scores."""
    weighted_sum = (
        WEIGHTS["consensus"] * consensus
        + WEIGHTS["reliability"] * reliability
        + WEIGHTS["software"] * software
        + WEIGHTS["diversity"] * diversity
        + WEIGHTS["identity"] * identity
    ) // 100
    return min(weighted_sum, consensus + CONSENSUS_GATE_MARGIN)


def _final_score_for(validator: ValidatorScore) -> int:
    return compute_final_score(
        validator.consensus,
        validator.reliability,
        validator.software,
        validator.diversity,
        validator.identity,
    )


def apply_formula(scoring_result: ScoringResult) -> ScoringResult:
    """Return a copy of the result whose overall scores are the final scores.

    The input result keeps the model's advisory scores untouched — it is
    what the artifacts publish as pure model output. The returned copy is
    what UNL selection consumes.
    """
    return scoring_result.model_copy(
        update={
            "validator_scores": [
                v.model_copy(update={"score": _final_score_for(v)})
                for v in scoring_result.validator_scores
            ]
        }
    )


def build_final_scores_artifact(scoring_result: ScoringResult) -> dict:
    """Build the ``outputs/final_scores.json`` artifact content.

    Self-contained: carries the formula version and parameters alongside
    the per-validator advisory model score and deterministic final score,
    sorted by master key for canonical hashing.
    """
    return {
        "formula": {
            "version": FORMULA_VERSION,
            "weights": dict(WEIGHTS),
            "consensus_gate_margin": CONSENSUS_GATE_MARGIN,
        },
        "scores": [
            {
                "master_key": v.master_key,
                "model_score": v.score,
                "final_score": _final_score_for(v),
            }
            for v in sorted(
                scoring_result.validator_scores, key=lambda v: v.master_key
            )
        ],
    }
