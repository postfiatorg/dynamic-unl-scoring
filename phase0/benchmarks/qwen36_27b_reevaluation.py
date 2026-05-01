"""Compare the current Dynamic UNL model against Qwen3.6 27B."""

import argparse
import itertools
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scoring_utils import (  # noqa: E402
    DEFAULT_MAX_TOKENS,
    DEFAULT_RUNS_PER_MODEL,
    JSON_RESPONSE_FORMAT,
    build_historical_v1_layer,
    build_scoring_v2_layer,
    build_result_summary,
    compute_score_stats,
    load_snapshot,
    normalize_score,
    parse_decimal,
    run_single,
)

RESULTS_ROOT = REPO_ROOT / "phase0" / "results" / "qwen36-27b-reevaluation"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_AA_BENCHMARKS_URL = (
    "https://openrouter.ai/api/internal/v1/artificial-analysis-benchmarks"
)
TOP_UNL_SIZE = 35
SCORE_DIMENSIONS = ("consensus", "reliability", "software", "diversity", "identity")
MODEL_PRICES_PER_MILLION = {
    "qwen/qwen3-next-80b-a3b-instruct": {
        "prompt": 0.09,
        "completion": 1.10,
    },
    "qwen/qwen3.6-27b": {
        "prompt": 0.325,
        "completion": 3.25,
    },
}

MODELS = [
    {
        "name": "incumbent-qwen3-next-80b-a3b-instruct",
        "model_id": "qwen/qwen3-next-80b-a3b-instruct",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    },
    {
        "name": "candidate-qwen3.6-27b",
        "model_id": "qwen/qwen3.6-27b",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {"reasoning": {"effort": "none"}},
        "response_format": JSON_RESPONSE_FORMAT,
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reevaluate qwen/qwen3.6-27b for Dynamic UNL scoring."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS_PER_MODEL,
        help=f"Runs per model/layer (default: {DEFAULT_RUNS_PER_MODEL}).",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Run only the named model. Can be passed multiple times.",
    )
    parser.add_argument(
        "--layer",
        action="append",
        dest="layers",
        help="Run only the named layer: historical_v1 or scoring_v2.",
    )
    parser.add_argument(
        "--session-name",
        help="Results subdirectory name. Default: current local timestamp.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing run_N.json files instead of skipping them.",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Only regenerate metadata and analysis from existing results.",
    )
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True))


def select_named(requested: list[str] | None, available: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not requested:
        return available

    by_name = {item["name"]: item for item in available}
    missing = sorted(set(requested) - set(by_name))
    if missing:
        raise ValueError(
            f"Unknown selection(s): {', '.join(missing)}. "
            f"Available: {', '.join(sorted(by_name))}"
        )
    return [by_name[name] for name in requested]


def fetch_openrouter_metadata(model_ids: list[str]) -> dict[str, Any]:
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={"User-Agent": "dynamic-unl-model-reevaluation/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    by_id = {item["id"]: item for item in payload.get("data", [])}
    selected = {}
    for model_id in model_ids:
        item = by_id.get(model_id)
        if not item:
            selected[model_id] = {"error": "model not found in OpenRouter response"}
            continue
        selected[model_id] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "created": item.get("created"),
            "context_length": item.get("context_length"),
            "architecture": item.get("architecture"),
            "pricing": item.get("pricing"),
            "top_provider": item.get("top_provider"),
            "supported_parameters": item.get("supported_parameters"),
            "canonical_slug": item.get("canonical_slug"),
            "hugging_face_id": item.get("hugging_face_id"),
            "per_request_limits": item.get("per_request_limits"),
        }
    return selected


def fetch_openrouter_aa_benchmarks(model_ids: list[str]) -> dict[str, Any]:
    selected = {}
    for model_id in model_ids:
        query = urllib.parse.urlencode({"slug": model_id})
        request = urllib.request.Request(
            f"{OPENROUTER_AA_BENCHMARKS_URL}?{query}",
            headers={"User-Agent": "dynamic-unl-model-reevaluation/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        selected[model_id] = payload
    return selected


def run_benchmarks(
    args: argparse.Namespace,
    session_dir: Path,
    layers: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    for layer in layers:
        layer_dir = session_dir / layer["name"]
        for model_cfg in models:
            model_dir = layer_dir / model_cfg["name"]
            model_dir.mkdir(parents=True, exist_ok=True)
            print(
                f"\nBenchmarking {layer['name']} / "
                f"{model_cfg['name']} ({model_cfg['model_id']})"
            )

            for run_num in range(1, args.runs + 1):
                output_path = model_dir / f"run_{run_num}.json"
                if output_path.exists() and not args.force:
                    existing = json.loads(output_path.read_text())
                    print(
                        f"    Skipping existing {output_path.name}: "
                        f"{build_result_summary(existing)}"
                    )
                    continue

                result = run_single(
                    client,
                    model_cfg,
                    layer["messages"],
                    run_num,
                    layer["validator_id_map"],
                    set(layer.get("allowed_extra_keys", [])),
                )
                result["benchmark_layer"] = layer["name"]
                result["prompt_path"] = layer["prompt"]
                result["snapshot_path"] = layer["snapshot"]
                output_path.write_text(json.dumps(result, indent=2))
                print(f"    {build_result_summary(result)}")


def load_runs(session_dir: Path, layer_name: str, model_name: str) -> list[dict[str, Any]]:
    model_dir = session_dir / layer_name / model_name
    if not model_dir.exists():
        return []
    return [
        json.loads(path.read_text())
        for path in sorted(model_dir.glob("run_*.json"))
    ]


def score_items(run: dict[str, Any]) -> dict[str, int]:
    scores = {}
    for master_key, entry in (run.get("scores") or {}).items():
        if isinstance(entry, dict):
            score = normalize_score(entry.get("score"))
            if score is not None:
                scores[master_key] = score
    return scores


def top_unl(scores: dict[str, int]) -> set[str]:
    return {
        master_key
        for master_key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[
            :TOP_UNL_SIZE
        ]
    }


def mean_score_map(runs: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for run in runs:
        if not run.get("complete_result"):
            continue
        for master_key, score in score_items(run).items():
            grouped[master_key].append(score)
    return {
        master_key: round(statistics.mean(scores), 2)
        for master_key, scores in grouped.items()
        if scores
    }


def summarize_dimension_compliance(runs: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = []
    for run in runs:
        parsed = run.get("scores_by_validator_id")
        if not isinstance(parsed, dict):
            continue
        validator_ids = [
            validator_id
            for validator_id in run.get("validator_id_map", {})
            if isinstance(parsed.get(validator_id), dict)
        ]
        invalid = []
        for validator_id in validator_ids:
            entry = parsed[validator_id]
            for dimension in SCORE_DIMENSIONS:
                if normalize_score(entry.get(dimension)) is None:
                    invalid.append(f"{validator_id}.{dimension}")
        summaries.append(
            {
                "run": run.get("run"),
                "network_summary_present": isinstance(
                    parsed.get("network_summary"), str
                )
                and bool(parsed.get("network_summary", "").strip()),
                "invalid_dimension_fields": invalid,
            }
        )

    return {
        "runs_checked": len(summaries),
        "runs_with_network_summary": sum(
            1 for item in summaries if item["network_summary_present"]
        ),
        "total_invalid_dimension_fields": sum(
            len(item["invalid_dimension_fields"]) for item in summaries
        ),
        "details": summaries,
    }


def summarize_reasoning(runs: list[dict[str, Any]]) -> dict[str, Any]:
    reasonings = []
    numeric_pattern = re.compile(r"\d")
    for run in runs:
        if not run.get("complete_result"):
            continue
        for entry in (run.get("scores") or {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("reasoning"), str):
                reasonings.append(entry["reasoning"].strip())

    if not reasonings:
        return {
            "reasoning_count": 0,
            "mean_reasoning_chars": None,
            "numeric_evidence_rate": None,
        }

    return {
        "reasoning_count": len(reasonings),
        "mean_reasoning_chars": round(
            statistics.mean(len(reasoning) for reasoning in reasonings), 1
        ),
        "numeric_evidence_rate": round(
            sum(1 for reasoning in reasonings if numeric_pattern.search(reasoning))
            / len(reasonings),
            3,
        ),
    }


def estimate_cost(run: dict[str, Any]) -> float | None:
    prices = MODEL_PRICES_PER_MILLION.get(run.get("model"))
    prompt_tokens = run.get("prompt_tokens")
    completion_tokens = run.get("completion_tokens")
    if not prices or prompt_tokens is None or completion_tokens is None:
        return None
    return round(
        (prompt_tokens / 1_000_000 * prices["prompt"])
        + (completion_tokens / 1_000_000 * prices["completion"]),
        6,
    )


def agreement_groups() -> dict[str, list[str]]:
    groups = {
        "strong_30d_ge_0.999": [],
        "marginal_30d_0.99_to_0.999": [],
        "weak_30d_lt_0.99": [],
        "failed_30d_le_0.01": [],
    }
    for validator in load_snapshot()["validators"]:
        master_key = validator["master_key"]
        score = parse_decimal(validator.get("agreement_30d_score"))
        if score is None:
            continue
        if score >= 0.999:
            groups["strong_30d_ge_0.999"].append(master_key)
        elif score >= 0.99:
            groups["marginal_30d_0.99_to_0.999"].append(master_key)
        elif score <= 0.01:
            groups["failed_30d_le_0.01"].append(master_key)
        else:
            groups["weak_30d_lt_0.99"].append(master_key)
    return groups


def summarize_penalty_calibration(mean_scores: dict[str, float]) -> dict[str, Any]:
    summary = {}
    for group_name, master_keys in agreement_groups().items():
        values = [mean_scores[key] for key in master_keys if key in mean_scores]
        summary[group_name] = {
            "validator_count": len(master_keys),
            "scored_count": len(values),
            "mean_score": round(statistics.mean(values), 2) if values else None,
        }
    strong = summary["strong_30d_ge_0.999"]["mean_score"]
    weak = summary["weak_30d_lt_0.99"]["mean_score"]
    failed = summary["failed_30d_le_0.01"]["mean_score"]
    summary["strong_minus_weak_delta"] = (
        round(strong - weak, 2) if strong is not None and weak is not None else None
    )
    summary["strong_minus_failed_delta"] = (
        round(strong - failed, 2) if strong is not None and failed is not None else None
    )
    return summary


def summarize_model_runs(
    runs: list[dict[str, Any]], expects_dimensions: bool
) -> dict[str, Any]:
    complete_runs = [run for run in runs if run.get("complete_result")]
    costs = [cost for run in runs if (cost := estimate_cost(run)) is not None]
    score_maps = [score_items(run) for run in complete_runs]
    mean_scores = mean_score_map(complete_runs)

    score_spreads = {}
    for master_key in mean_scores:
        values = [scores[master_key] for scores in score_maps if master_key in scores]
        if values:
            score_spreads[master_key] = max(values) - min(values)

    top_sets = [top_unl(scores) for scores in score_maps if len(scores) >= TOP_UNL_SIZE]
    pairwise_overlaps = [
        len(left & right)
        for left, right in itertools.combinations(top_sets, 2)
    ]

    return {
        "runs": len(runs),
        "complete_runs": len(complete_runs),
        "json_valid_runs": sum(1 for run in runs if run.get("json_valid")),
        "finish_reasons": sorted(
            {str(run.get("finish_reason")) for run in runs if run.get("finish_reason")}
        ),
        "mean_elapsed_seconds": round(
            statistics.mean(run.get("elapsed_seconds", 0) for run in runs), 2
        )
        if runs
        else None,
        "mean_prompt_tokens": round(
            statistics.mean(
                run.get("prompt_tokens", 0) for run in runs if run.get("prompt_tokens")
            ),
            1,
        )
        if any(run.get("prompt_tokens") for run in runs)
        else None,
        "mean_completion_tokens": round(
            statistics.mean(
                run.get("completion_tokens", 0)
                for run in runs
                if run.get("completion_tokens")
            ),
            1,
        )
        if any(run.get("completion_tokens") for run in runs)
        else None,
        "mean_estimated_cost_usd": round(statistics.mean(costs), 6)
        if costs
        else None,
        "score_stats_by_run": [
            run.get("score_stats") for run in complete_runs if run.get("score_stats")
        ],
        "mean_score_stats": compute_score_stats(
            {
                master_key: {"score": round(score)}
                for master_key, score in mean_scores.items()
            },
            list(mean_scores),
        ),
        "per_validator_spread": {
            "mean": round(statistics.mean(score_spreads.values()), 2)
            if score_spreads
            else None,
            "max": max(score_spreads.values()) if score_spreads else None,
            "within_0": sum(1 for spread in score_spreads.values() if spread == 0),
            "within_3": sum(1 for spread in score_spreads.values() if spread <= 3),
            "within_5": sum(1 for spread in score_spreads.values() if spread <= 5),
            "over_10": sum(1 for spread in score_spreads.values() if spread > 10),
        },
        "top35_unl": {
            "pairwise_overlap_mean": round(statistics.mean(pairwise_overlaps), 2)
            if pairwise_overlaps
            else None,
            "pairwise_overlap_min": min(pairwise_overlaps)
            if pairwise_overlaps
            else None,
            "borderline_count": len(set.union(*top_sets) - set.intersection(*top_sets))
            if top_sets
            else None,
            "always_in_count": len(set.intersection(*top_sets)) if top_sets else None,
        },
        "dimension_compliance": summarize_dimension_compliance(runs)
        if expects_dimensions
        else {"not_applicable": True},
        "reasoning": summarize_reasoning(complete_runs),
        "penalty_calibration": summarize_penalty_calibration(mean_scores),
        "mean_scores_by_master_key": mean_scores,
    }


def summarize_cross_model(layer_summary: dict[str, Any]) -> dict[str, Any]:
    incumbent = layer_summary.get("incumbent-qwen3-next-80b-a3b-instruct", {})
    candidate = layer_summary.get("candidate-qwen3.6-27b", {})
    incumbent_scores = incumbent.get("mean_scores_by_master_key") or {}
    candidate_scores = candidate.get("mean_scores_by_master_key") or {}
    shared_keys = sorted(set(incumbent_scores) & set(candidate_scores))
    if not shared_keys:
        return {}

    deltas = {
        key: round(candidate_scores[key] - incumbent_scores[key], 2)
        for key in shared_keys
    }
    incumbent_top = top_unl({key: round(value) for key, value in incumbent_scores.items()})
    candidate_top = top_unl({key: round(value) for key, value in candidate_scores.items()})
    return {
        "shared_validator_count": len(shared_keys),
        "candidate_minus_incumbent_mean_delta": round(
            statistics.mean(deltas.values()), 2
        ),
        "candidate_minus_incumbent_max_abs_delta": round(
            max(abs(delta) for delta in deltas.values()), 2
        ),
        "top35_overlap_count": len(incumbent_top & candidate_top),
        "top35_symmetric_difference_count": len(incumbent_top ^ candidate_top),
        "largest_score_deltas": sorted(
            deltas.items(), key=lambda item: abs(item[1]), reverse=True
        )[:10],
    }


def write_analysis(session_dir: Path, layers: list[dict[str, Any]], models: list[dict[str, Any]]) -> None:
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_unl_size": TOP_UNL_SIZE,
        "prices_per_million_tokens_usd": MODEL_PRICES_PER_MILLION,
        "layers": {},
        "cross_model": {},
    }

    for layer in layers:
        layer_name = layer["name"]
        layer_summary = {}
        for model in models:
            runs = load_runs(session_dir, layer_name, model["name"])
            layer_summary[model["name"]] = summarize_model_runs(
                runs, expects_dimensions=layer_name == "scoring_v2"
            )
        summary["layers"][layer_name] = layer_summary
        summary["cross_model"][layer_name] = summarize_cross_model(layer_summary)

    write_json(session_dir / "analysis_summary.json", summary)


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be >= 1")

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    available_layers = [build_historical_v1_layer(), build_scoring_v2_layer()]
    layers = select_named(args.layers, available_layers)
    models = select_named(args.models, MODELS)

    session_name = args.session_name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = RESULTS_ROOT / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_model_layer": args.runs,
        "models": [
            {
                key: model[key]
                for key in (
                    "name",
                    "model_id",
                    "params",
                    "extra_body",
                    "response_format",
                )
            }
            for model in models
        ],
        "layers": [
            {
                "name": layer["name"],
                "prompt": layer["prompt"],
                "snapshot": layer["snapshot"],
                "validator_count": len(layer["validator_id_map"]),
            }
            for layer in layers
        ],
        "notes": [
            "OpenRouter is used only as the provider-mediated benchmark harness.",
            "Production determinism still requires self-hosted Modal/SGLang validation.",
            "scoring_v2 normalizes the Phase 0 snapshot into the current nested snapshot schema.",
        ],
    }
    write_json(session_dir / "metadata.json", metadata)

    try:
        openrouter_metadata = fetch_openrouter_metadata(
            [model["model_id"] for model in models]
        )
    except Exception as exc:  # noqa: BLE001
        openrouter_metadata = {"error": str(exc)}
    write_json(session_dir / "openrouter_model_metadata.json", openrouter_metadata)

    try:
        openrouter_aa_benchmarks = fetch_openrouter_aa_benchmarks(
            [model["model_id"] for model in models]
        )
    except Exception as exc:  # noqa: BLE001
        openrouter_aa_benchmarks = {"error": str(exc)}
    write_json(
        session_dir / "openrouter_artificial_analysis_benchmarks.json",
        openrouter_aa_benchmarks,
    )

    if not args.skip_benchmark:
        run_benchmarks(args, session_dir, layers, models)

    write_analysis(session_dir, layers, models)
    print(f"\nResults saved to {session_dir}")
    print(f"Analysis summary: {session_dir / 'analysis_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
