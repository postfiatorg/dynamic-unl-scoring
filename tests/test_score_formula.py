"""Tests for the deterministic final-score formula (score formula v1)."""

from itertools import product

from scoring_service.services.response_parser import ScoringResult, ValidatorScore
from scoring_service.services.score_formula import (
    CONSENSUS_GATE_MARGIN,
    FORMULA_VERSION,
    WEIGHTS,
    apply_formula,
    build_final_scores_artifact,
    compute_final_score,
)


def _validator(master_key, score, consensus, reliability, software, diversity, identity):
    return ValidatorScore(
        master_key=master_key,
        score=score,
        consensus=consensus,
        reliability=reliability,
        software=software,
        diversity=diversity,
        identity=identity,
        reasoning="test",
    )


def _result(validators):
    return ScoringResult(
        validator_scores=validators,
        network_summary="test",
        raw_response="{}",
        complete=True,
        errors=[],
    )


class TestComputeFinalScore:
    def test_parameters_match_design_doc(self):
        assert FORMULA_VERSION == 1
        assert WEIGHTS == {
            "consensus": 50,
            "reliability": 20,
            "software": 10,
            "diversity": 10,
            "identity": 10,
        }
        assert sum(WEIGHTS.values()) == 100
        assert CONSENSUS_GATE_MARGIN == 25

    def test_worked_examples_from_design_doc(self):
        # The five rows of the worked-examples table in
        # docs/DeterministicFinalScore.md.
        assert compute_final_score(100, 90, 100, 40, 80) == 90
        assert compute_final_score(100, 85, 100, 50, 80) == 90
        assert compute_final_score(99, 91, 100, 55, 75) == 90
        assert compute_final_score(96, 70, 100, 62, 50) == 83
        assert compute_final_score(0, 85, 100, 40, 80) == 25

    def test_bounds(self):
        assert compute_final_score(0, 0, 0, 0, 0) == 0
        assert compute_final_score(100, 100, 100, 100, 100) == 100

    def test_gate_binds_only_when_consensus_lags(self):
        # Healthy consensus: the gate never binds (cap is above 100).
        assert compute_final_score(100, 0, 0, 0, 0) == 50
        # Offline: the gate caps at consensus + margin.
        assert compute_final_score(0, 100, 100, 100, 100) == CONSENSUS_GATE_MARGIN

    def test_floor_division_discards_remainder(self):
        # weighted_sum = (50*99 + 20*91 + 10*100 + 10*55 + 10*75) = 9070 -> 90
        assert compute_final_score(99, 91, 100, 55, 75) == 90

    def test_identical_subscores_yield_identical_finals(self):
        result = _result([
            _validator("nA", 92, 97, 83, 100, 55, 80),
            _validator("nB", 88, 97, 83, 100, 55, 80),
        ])
        finals = [v.score for v in apply_formula(result).validator_scores]
        assert finals[0] == finals[1]

    def test_dominance_monotone_in_every_dimension(self):
        # Weakly better sub-scores can never lower the final score. Sampled
        # over a coarse grid, stepping each dimension up independently.
        grid = [0, 40, 80, 100]
        for vector in product(grid, repeat=5):
            base = compute_final_score(*vector)
            for dim in range(5):
                if vector[dim] == 100:
                    continue
                bumped = list(vector)
                bumped[dim] = 100
                assert compute_final_score(*bumped) >= base


class TestApplyFormula:
    def test_returns_final_scores_and_preserves_input(self):
        original = _result([
            _validator("nA", 92, 100, 90, 100, 40, 80),
            _validator("nB", 20, 0, 85, 100, 40, 80),
        ])
        final = apply_formula(original)

        assert [v.score for v in final.validator_scores] == [90, 25]
        # The input result keeps the model's advisory scores untouched.
        assert [v.score for v in original.validator_scores] == [92, 20]

    def test_preserves_subscores_identity_and_result_fields(self):
        original = _result([_validator("nA", 92, 100, 90, 100, 40, 80)])
        final = apply_formula(original)

        validator = final.validator_scores[0]
        assert validator.master_key == "nA"
        assert (validator.consensus, validator.reliability, validator.software,
                validator.diversity, validator.identity) == (100, 90, 100, 40, 80)
        assert final.complete is original.complete
        assert final.raw_response == original.raw_response


class TestBuildFinalScoresArtifact:
    def test_artifact_is_self_contained_and_sorted(self):
        result = _result([
            _validator("nB", 20, 0, 85, 100, 40, 80),
            _validator("nA", 92, 100, 90, 100, 40, 80),
        ])
        artifact = build_final_scores_artifact(result)

        assert artifact["formula"] == {
            "version": FORMULA_VERSION,
            "weights": WEIGHTS,
            "consensus_gate_margin": CONSENSUS_GATE_MARGIN,
        }
        assert artifact["scores"] == [
            {"master_key": "nA", "model_score": 92, "final_score": 90},
            {"master_key": "nB", "model_score": 20, "final_score": 25},
        ]
