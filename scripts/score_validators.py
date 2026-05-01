"""Score validators against a self-hosted endpoint (Modal, RunPod, local SGLang).

Usage:
    python scripts/score_validators.py --url http://host:8000/v1
    python scripts/score_validators.py --url http://host:8000/v1 --runs 3 --session-name test
    python scripts/score_validators.py --url http://host:8000/v1 --prompt-version v2 --disable-thinking
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for path in (SCRIPT_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scoring_utils import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_SESSION_TIME_FORMAT,
    JSON_RESPONSE_FORMAT,
    PROMPT_VERSION_CHOICES,
    build_prompt_layer,
    build_result_summary,
    load_result,
    run_single,
    validate_scoring_v2_contract,
)
from query import create_client

DEFAULT_RUNS = 5
DEFAULT_MODEL_NAME = "qwen36-27b-fp8"
DEFAULT_MODEL_ID = "Qwen/Qwen3.6-27B-FP8"
DEFAULT_PROMPT_VERSION = "v2"
RESULTS_DIR = REPO_ROOT / "phase0" / "results" / "modal"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score validators against a self-hosted endpoint."
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL (e.g. http://host:8000/v1)",
    )
    parser.add_argument(
        "--model-id", default=DEFAULT_MODEL_ID,
        help=f"Model name for the API request (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--model-name", default=DEFAULT_MODEL_NAME,
        help=f"Short name for result directories (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--runs", type=int, default=DEFAULT_RUNS,
        help=f"Number of scoring runs (default: {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--prompt-version",
        choices=PROMPT_VERSION_CHOICES,
        default=DEFAULT_PROMPT_VERSION,
        help=(
            "Prompt contract to run. v1 matches the historical Modal baseline; "
            "v2 matches the active scoring contract."
        ),
    )
    parser.add_argument(
        "--disable-thinking",
        dest="disable_thinking",
        action="store_true",
        default=True,
        help=(
            "Use the default chat_template_kwargs.enable_thinking=false override "
            "for Qwen models that think by default."
        ),
    )
    parser.add_argument(
        "--enable-thinking",
        dest="disable_thinking",
        action="store_false",
        help="Omit the Qwen non-thinking chat template override.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing run files.",
    )
    parser.add_argument(
        "--session-name",
        help="Session subdirectory name. Default: current timestamp.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.runs < 1:
        print("Error: --runs must be >= 1.")
        return 1

    layer = build_prompt_layer(args.prompt_version)

    extra_body: dict[str, Any] = {}
    if args.disable_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    model_cfg = {
        "name": args.model_name,
        "model_id": args.model_id,
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": extra_body,
        "response_format": JSON_RESPONSE_FORMAT,
    }

    session_name = args.session_name or datetime.now().strftime(
        DEFAULT_SESSION_TIME_FORMAT
    )
    session_dir = RESULTS_DIR / model_cfg["name"] / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Loaded {layer['name']} prompt with "
        f"{len(layer['validator_id_map'])} validators"
    )
    print(f"Endpoint: {args.url}")
    print(f"Model: {model_cfg['model_id']}")
    print(f"Saving results to {session_dir}")

    client = create_client(args.url)

    print(f"\nScoring with {model_cfg['name']} ({model_cfg['model_id']})")
    for run_num in range(1, args.runs + 1):
        output_path = session_dir / f"run_{run_num}.json"
        if output_path.exists() and not args.force:
            existing = load_result(output_path)
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
            set(layer["allowed_extra_keys"]),
        )
        result["benchmark_layer"] = layer["name"]
        result["prompt_version"] = args.prompt_version
        result["prompt_path"] = layer["prompt"]
        result["snapshot_path"] = layer["snapshot"]
        if args.prompt_version == "v2":
            result["scoring_v2_contract"] = validate_scoring_v2_contract(result)
        output_path.write_text(json.dumps(result, indent=2))
        print(f"    {build_result_summary(result)}")

    print(f"\nAll results saved to {session_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
