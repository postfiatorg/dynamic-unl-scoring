"""Replay frozen scoring rounds against a candidate model endpoint.

Unlike replay_prompt_variants.py, which re-renders prompts to test prompt
changes, this runner replays a round's frozen ``inputs/model_request.json``
verbatim except for the ``model`` field, so every output difference is
attributable to the candidate model alone.

Subcommands:

  fetch  — download a round's frozen inputs, manifest, and published
           production outputs from a scoring service into a local cache dir.
  run    — send the frozen request (model field swapped) to a candidate
           endpoint and save the raw response with its determinism
           fingerprint, in the same result shape replay_prompt_variants
           uses. Optional request-contract overrides (--enable-thinking,
           --max-tokens) are recorded in the saved artifact so deviations
           from the verbatim frozen request stay self-describing.
  check  — mechanical comparison of candidate outputs against the round's
           published production response: determinism across repeats (content
           and reasoning fingerprints), parse validity under the production
           parser, per-dimension drift, and final-score plus UNL-selection
           reproduction using the round's own frozen selector parameters
           (era-aware: rounds whose manifest pins a score formula compare
           formula finals; older rounds compare the model's overall scores
           directly). An optional --mode-baseline result from a prior run of
           the same model isolates a request-contract change from a model
           change.
"""

import argparse
import copy
import hashlib
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for path in (SCRIPT_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query import create_client  # noqa: E402

from scoring_service.services.response_parser import parse_response  # noqa: E402
from scoring_service.services.score_formula import compute_final_score  # noqa: E402
from scoring_service.services.unl_selector import select_unl  # noqa: E402

SERVICE_URLS = {
    "testnet": "https://scoring-testnet.postfiat.org",
    "devnet": "https://scoring-devnet.postfiat.org",
}
INPUT_FILES = (
    "inputs/model_request.json",
    "inputs/validator_map.json",
    "inputs/previous_unl.json",
    "runtime/execution_manifest.json",
)
OUTPUT_FILES = (
    "outputs/model_response.json",
    "outputs/selected_unl.json",
)
REQUEST_PASSTHROUGH_KEYS = ("extra_body", "max_tokens", "temperature", "response_format")
DIMENSIONS = ("consensus", "reliability", "software", "diversity", "identity")
DEFAULT_TIMEOUT_SECONDS = 2100


def _fetch_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.load(response)
    except Exception:
        return None


def fetch_round(network: str, round_number: int, cache_dir: Path) -> int:
    base = SERVICE_URLS[network]
    round_dir = cache_dir / f"{network}-r{round_number}"
    missing_required = False

    for rel_path, route in [
        *[(p, f"{base}/api/scoring/rounds/{round_number}/input/{p}") for p in INPUT_FILES],
        *[(p, f"{base}/api/scoring/rounds/{round_number}/{p}") for p in OUTPUT_FILES],
    ]:
        payload = _fetch_json(route)
        target = round_dir / rel_path
        if payload is None:
            print(f"  {rel_path}: MISSING")
            if rel_path in ("inputs/model_request.json", "outputs/model_response.json"):
                missing_required = True
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=1))
        print(f"  {rel_path}: {target.stat().st_size} bytes")

    if missing_required:
        print(f"{network} round {round_number}: required files missing — round not replayable")
        return 1
    return 0


def _load(round_dir: Path, rel_path: str) -> dict | None:
    path = round_dir / rel_path
    if not path.exists():
        return None
    return json.loads(path.read_text())


def run_candidate(
    round_dir: Path,
    model: str,
    url: str,
    out_path: Path,
    timeout: float,
    enable_thinking: bool = False,
    max_tokens: int | None = None,
) -> None:
    frozen = _load(round_dir, "inputs/model_request.json")
    if frozen is None:
        raise SystemExit(f"no frozen request in {round_dir}")
    validator_map = _load(round_dir, "inputs/validator_map.json") or {}

    request = {key: frozen[key] for key in REQUEST_PASSTHROUGH_KEYS if key in frozen}
    request["messages"] = frozen["messages"]
    request["model"] = model
    overrides: dict = {}
    if enable_thinking:
        extra_body = copy.deepcopy(request.get("extra_body")) or {}
        extra_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = True
        request["extra_body"] = extra_body
        overrides["enable_thinking"] = True
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
        overrides["max_tokens"] = max_tokens

    endpoint = url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint = f"{endpoint}/v1"
    client = create_client(endpoint, timeout=timeout)

    print(f"calling {model} for {round_dir.name} (timeout {timeout:.0f}s)...")
    requested_at = datetime.now(timezone.utc).isoformat()
    start = time.time()
    response = client.chat.completions.create(**request)
    duration = time.time() - start
    choice = response.choices[0]
    content = choice.message.content or ""
    reasoning = getattr(choice.message, "reasoning_content", None)
    if reasoning is None:
        reasoning = getattr(choice.message, "reasoning", None)

    result = {
        "variant": f"candidate:{model}",
        "round": round_dir.name,
        "endpoint": endpoint,
        "requested_at": requested_at,
        "duration_seconds": round(duration, 1),
        "model": model,
        "request_overrides": overrides,
        "finish_reason": choice.finish_reason,
        "usage": response.usage.model_dump() if response.usage else None,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "reasoning_sha256": (
            hashlib.sha256(reasoning.encode()).hexdigest() if reasoning is not None else None
        ),
        "validator_id_map": {
            vid: entry["master_key"] for vid, entry in validator_map.items()
        },
        "content": content,
        "reasoning_content": reasoning,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1))
    print(
        f"{round_dir.name}: {duration:.1f}s, content sha256 "
        f"{result['content_sha256'][:16]}..., saved {out_path}"
    )


def _parse(round_dir: Path, raw_content: str):
    return parse_response(raw_content, _load(round_dir, "inputs/validator_map.json") or {})


def _scores_by_master(result) -> dict[str, dict]:
    return {
        v.master_key: {dim: getattr(v, dim) for dim in DIMENSIONS}
        for v in result.validator_scores
    }


def _selection_scores(manifest: dict, parsed) -> dict[str, int]:
    """Per-era authoritative selection score: formula finals when the round
    pinned a score formula, the model's overall score otherwise."""
    if "score_formula" in manifest.get("code", {}):
        return {
            v.master_key: compute_final_score(
                v.consensus, v.reliability, v.software, v.diversity, v.identity
            )
            for v in parsed.validator_scores
        }
    return {v.master_key: v.score for v in parsed.validator_scores}


def check_round(
    round_dir: Path,
    candidate_paths: list[Path],
    mode_baseline_path: Path | None = None,
) -> dict:
    manifest = _load(round_dir, "runtime/execution_manifest.json") or {}
    prompt_version = manifest.get("code", {}).get("prompt", {}).get("version", "?")
    selector_params = manifest.get("code", {}).get("selector", {}).get("parameters", {})
    baseline = _load(round_dir, "outputs/model_response.json") or {}
    baseline_content = baseline.get("raw_response") or baseline.get("content") or ""
    published_unl = (_load(round_dir, "outputs/selected_unl.json") or {}).get("unl")
    previous = (_load(round_dir, "inputs/previous_unl.json") or {}).get("previous_unl")

    candidates = [json.loads(p.read_text()) for p in candidate_paths]
    report: dict = {"round": round_dir.name, "prompt_version": prompt_version}

    fingerprints = {(c["content_sha256"], c.get("reasoning_sha256")) for c in candidates}
    report["repeats"] = len(candidates)
    report["deterministic"] = len(fingerprints) == 1 if len(candidates) > 1 else None
    report["content_sha256"] = sorted({c["content_sha256"] for c in candidates})
    reasoning_hashes = sorted(
        {c["reasoning_sha256"] for c in candidates if c.get("reasoning_sha256")}
    )
    if reasoning_hashes:
        report["reasoning_sha256"] = reasoning_hashes
    finish_reasons = sorted({c["finish_reason"] for c in candidates if c.get("finish_reason")})
    if finish_reasons:
        report["finish_reasons"] = finish_reasons

    parsed_candidate = _parse(round_dir, candidates[0]["content"])
    report["candidate_parse_complete"] = parsed_candidate.complete
    report["candidate_parse_errors"] = list(parsed_candidate.errors)
    parsed_baseline = _parse(round_dir, baseline_content)
    report["baseline_parse_complete"] = parsed_baseline.complete

    if not (parsed_candidate.complete and parsed_baseline.complete):
        return report

    cand = _scores_by_master(parsed_candidate)
    base = _scores_by_master(parsed_baseline)
    common = sorted(set(cand) & set(base))
    report["validators_compared"] = len(common)
    report["dimension_mean_abs_delta"] = {
        dim: round(statistics.mean(abs(cand[mk][dim] - base[mk][dim]) for mk in common), 2)
        for dim in DIMENSIONS
    }

    cand_sel = _selection_scores(manifest, parsed_candidate)
    base_sel = _selection_scores(manifest, parsed_baseline)
    deltas = sorted(abs(cand_sel[mk] - base_sel[mk]) for mk in common)
    report["selection_score_mean_abs_delta"] = round(statistics.mean(deltas), 2)
    report["selection_score_max_abs_delta"] = deltas[-1] if deltas else 0

    def _select(scores: dict[str, int]) -> list[str]:
        ranked = parsed_candidate.model_copy(
            update={
                "validator_scores": [
                    v.model_copy(update={"score": scores[v.master_key]})
                    for v in parsed_candidate.validator_scores
                    if v.master_key in scores
                ]
            }
        )
        return select_unl(
            ranked,
            previous_unl=previous,
            cutoff=selector_params.get("score_cutoff"),
            max_size=selector_params.get("max_size"),
            min_gap=selector_params.get("min_score_gap"),
        ).unl

    selectable = bool(previous is not None and selector_params)
    if selectable:
        candidate_unl = set(_select(cand_sel))
        report["published_unl_size"] = len(published_unl) if published_unl else None
        if published_unl is not None:
            overlap = candidate_unl & set(published_unl)
            report["unl_overlap_with_published"] = len(overlap)
            report["unl_seats_changed"] = len(candidate_unl ^ set(published_unl)) // 2

    if mode_baseline_path is not None:
        mode_baseline = json.loads(mode_baseline_path.read_text())
        parsed_mode = _parse(round_dir, mode_baseline["content"])
        report["mode_baseline_parse_complete"] = parsed_mode.complete
        if parsed_mode.complete:
            mode = _scores_by_master(parsed_mode)
            mode_common = sorted(set(cand) & set(mode))
            report["mode_baseline_validators_compared"] = len(mode_common)
            report["mode_baseline_dimension_mean_abs_delta"] = {
                dim: round(
                    statistics.mean(abs(cand[mk][dim] - mode[mk][dim]) for mk in mode_common), 2
                )
                for dim in DIMENSIONS
            }
            mode_sel = _selection_scores(manifest, parsed_mode)
            mode_deltas = sorted(abs(cand_sel[mk] - mode_sel[mk]) for mk in mode_common)
            report["mode_baseline_selection_score_mean_abs_delta"] = round(
                statistics.mean(mode_deltas), 2
            )
            report["mode_baseline_selection_score_max_abs_delta"] = (
                mode_deltas[-1] if mode_deltas else 0
            )
            if selectable:
                report["unl_seats_changed_vs_mode_baseline"] = (
                    len(set(_select(cand_sel)) ^ set(_select(mode_sel))) // 2
                )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--network", choices=sorted(SERVICE_URLS), required=True)
    fetch_parser.add_argument("--round", type=int, required=True)
    fetch_parser.add_argument("--dir", type=Path, required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--round-dir", type=Path, required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--url", required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_parser.add_argument("--enable-thinking", action="store_true")
    run_parser.add_argument("--max-tokens", type=int)

    check_parser = sub.add_parser("check")
    check_parser.add_argument("--round-dir", type=Path, required=True)
    check_parser.add_argument("--candidates", type=Path, nargs="+", required=True)
    check_parser.add_argument("--mode-baseline", type=Path)

    args = parser.parse_args()
    if args.command == "fetch":
        print(f"fetching {args.network} round {args.round}...")
        return fetch_round(args.network, args.round, args.dir)
    if args.command == "run":
        run_candidate(
            args.round_dir,
            args.model,
            args.url,
            args.out,
            args.timeout,
            enable_thinking=args.enable_thinking,
            max_tokens=args.max_tokens,
        )
        return 0
    report = check_round(args.round_dir, args.candidates, args.mode_baseline)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
