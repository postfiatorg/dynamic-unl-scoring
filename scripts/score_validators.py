"""Score validators against a self-hosted endpoint (Modal, RunPod, local SGLang).

Usage:
    python scripts/score_validators.py --url http://host:8000/v1
    python scripts/score_validators.py --url http://host:8000/v1 --runs 3 --session-name test
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from benchmark_models import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_SESSION_TIME_FORMAT,
    JSON_RESPONSE_FORMAT,
    REPO_ROOT,
    build_messages,
    build_result_summary,
    build_validator_prompt_data,
    load_prompt_template,
    load_result,
    load_snapshot,
    run_single,
)
from query import create_client

DEFAULT_RUNS = 5
DEFAULT_MODEL_NAME = "qwen3-next-80b-instruct"
DEFAULT_MODEL_ID = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
RESULTS_DIR = REPO_ROOT / "results" / "modal"


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

    system_prompt, user_template = load_prompt_template()
    snapshot = load_snapshot()
    prompt_validators, validator_id_map = build_validator_prompt_data(
        snapshot["validators"]
    )

    model_cfg = {
        "name": args.model_name,
        "model_id": args.model_id,
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    }

    session_name = args.session_name or datetime.now().strftime(
        DEFAULT_SESSION_TIME_FORMAT
    )
    session_dir = RESULTS_DIR / model_cfg["name"] / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loaded snapshot with {snapshot['validator_count']} validators")
    print(f"Endpoint: {args.url}")
    print(f"Model: {model_cfg['model_id']}")
    print(f"Saving results to {session_dir}")

    messages = build_messages(
        system_prompt,
        user_template,
        prompt_validators,
        snapshot.get("network_topology", {}),
    )

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
            client, model_cfg, messages, run_num, validator_id_map
        )
        output_path.write_text(json.dumps(result, indent=2))
        print(f"    {build_result_summary(result)}")

    print(f"\nAll results saved to {session_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
