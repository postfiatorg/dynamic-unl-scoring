"""Tests for the model-candidate replay harness."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from replay_model_candidate import (  # noqa: E402
    _selection_scores,
    check_round,
)
from scoring_service.services.response_parser import parse_response  # noqa: E402
from scoring_service.services.score_formula import compute_final_score  # noqa: E402

VALIDATOR_MAP = {
    "v001": {"master_key": "nHMASTER1", "signing_key": "nSIGN1"},
    "v002": {"master_key": "nHMASTER2", "signing_key": "nSIGN2"},
}


def _raw_response(scores: dict[str, dict]) -> str:
    return json.dumps({**scores, "network_summary": "test summary"})


def _score_entry(overall: int, c: int, r: int, s: int, d: int, i: int) -> dict:
    return {
        "score": overall,
        "consensus": c,
        "reliability": r,
        "software": s,
        "diversity": d,
        "identity": i,
        "reasoning": "test reasoning",
    }


def _parsed(scores: dict[str, dict]):
    result = parse_response(_raw_response(scores), VALIDATOR_MAP)
    assert result.complete, result.errors
    return result


class TestSelectionScores:
    def test_formula_round_uses_computed_finals(self):
        parsed = _parsed(
            {
                "v001": _score_entry(90, 100, 90, 100, 40, 80),
                "v002": _score_entry(50, 0, 85, 100, 40, 80),
            }
        )
        manifest = {"code": {"score_formula": {"version": 1}}}
        scores = _selection_scores(manifest, parsed)
        assert scores["nHMASTER1"] == compute_final_score(100, 90, 100, 40, 80)
        assert scores["nHMASTER2"] == compute_final_score(0, 85, 100, 40, 80)

    def test_pre_formula_round_uses_model_overall_score(self):
        parsed = _parsed(
            {
                "v001": _score_entry(91, 100, 90, 100, 40, 80),
                "v002": _score_entry(47, 0, 85, 100, 40, 80),
            }
        )
        manifest = {"code": {}}
        scores = _selection_scores(manifest, parsed)
        assert scores == {"nHMASTER1": 91, "nHMASTER2": 47}


class TestCheckRound:
    def _write_round(self, round_dir: Path, baseline_scores: dict) -> None:
        (round_dir / "inputs").mkdir(parents=True)
        (round_dir / "outputs").mkdir()
        (round_dir / "runtime").mkdir()
        (round_dir / "inputs/validator_map.json").write_text(json.dumps(VALIDATOR_MAP))
        (round_dir / "inputs/previous_unl.json").write_text(
            json.dumps({"previous_unl": ["nHMASTER1"]})
        )
        (round_dir / "runtime/execution_manifest.json").write_text(
            json.dumps(
                {
                    "code": {
                        "prompt": {"version": "v9"},
                        "score_formula": {"version": 1},
                        "selector": {
                            "parameters": {
                                "score_cutoff": 40,
                                "max_size": 2,
                                "min_score_gap": 3,
                            }
                        },
                    }
                }
            )
        )
        (round_dir / "outputs/model_response.json").write_text(
            json.dumps({"raw_response": _raw_response(baseline_scores)})
        )
        (round_dir / "outputs/selected_unl.json").write_text(
            json.dumps({"unl": ["nHMASTER1", "nHMASTER2"], "alternates": []})
        )

    def _candidate_file(self, path: Path, scores: dict) -> Path:
        content = _raw_response(scores)
        path.write_text(
            json.dumps(
                {
                    "variant": "candidate:test",
                    "round": "test-round",
                    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "content": content,
                }
            )
        )
        return path

    def test_identical_candidate_reports_zero_drift_and_full_overlap(self, tmp_path):
        scores = {
            "v001": _score_entry(90, 100, 90, 100, 40, 80),
            "v002": _score_entry(85, 95, 90, 100, 40, 80),
        }
        round_dir = tmp_path / "round"
        self._write_round(round_dir, scores)
        candidate = self._candidate_file(tmp_path / "cand.json", scores)

        single_report = check_round(round_dir, [candidate])
        assert single_report["deterministic"] is None

        report = check_round(round_dir, [candidate, candidate])
        assert report["deterministic"] is True
        assert report["candidate_parse_complete"] is True
        assert report["validators_compared"] == 2
        assert all(v == 0 for v in report["dimension_mean_abs_delta"].values())
        assert report["unl_overlap_with_published"] == 2
        assert report["unl_seats_changed"] == 0

    def test_divergent_repeats_flagged_nondeterministic(self, tmp_path):
        scores_a = {
            "v001": _score_entry(90, 100, 90, 100, 40, 80),
            "v002": _score_entry(85, 95, 90, 100, 40, 80),
        }
        scores_b = {
            "v001": _score_entry(90, 100, 95, 100, 40, 80),
            "v002": _score_entry(85, 95, 90, 100, 40, 80),
        }
        round_dir = tmp_path / "round"
        self._write_round(round_dir, scores_a)
        cand_a = self._candidate_file(tmp_path / "a.json", scores_a)
        cand_b = self._candidate_file(tmp_path / "b.json", scores_b)

        report = check_round(round_dir, [cand_a, cand_b])

        assert report["deterministic"] is False
        assert len(report["content_sha256"]) == 2
