"""Test the RunPod-hosted Qwen3-235B endpoint with the validator scoring prompt."""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "benchmarks" / "results"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from scoring_utils import (
    build_messages,
    build_validator_prompt_data,
    compute_score_stats,
    extract_answer_payload,
    extract_reasoning_text,
    load_prompt_template,
    load_snapshot,
    normalize_text_blob,
    remap_scores_to_master_keys,
    to_serializable,
    validate_scores,
)

RUNPOD_MODEL_ID = "Qwen/Qwen3-235B-A22B-GPTQ-Int4"
MAX_TOKENS = 16384
TEMPERATURE = 0


def get_runpod_client() -> OpenAI:
    api_key = os.environ.get("RUNPOD_API_KEY")
    endpoint_id = os.environ.get("RUNPOD_ENDPOINT_ID")
    if not api_key or not endpoint_id:
        print("Error: RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID must be set.")
        print("Copy .env.example to .env and fill in the RunPod values.")
        sys.exit(1)

    return OpenAI(
        base_url=f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1",
        api_key=api_key,
    )


def run_scoring(client: OpenAI, messages: list, validator_id_map: dict[str, str]) -> dict:
    expected_validator_ids = list(validator_id_map)
    expected_master_keys = [validator_id_map[vid] for vid in expected_validator_ids]

    print("Sending scoring request to RunPod endpoint...")
    start = time.time()
    try:
        response = client.chat.completions.create(
            model=RUNPOD_MODEL_ID,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        elapsed = time.time() - start
    except Exception as exc:
        elapsed = time.time() - start
        print(f"API error after {elapsed:.1f}s: {exc}")
        return {"error": str(exc), "elapsed_seconds": round(elapsed, 2)}

    print(f"Response received in {elapsed:.1f}s")

    response_payload = to_serializable(response)
    usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    choice = choices[0] if choices else {}
    message = choice.get("message") if isinstance(choice, dict) else None
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

    extracted = extract_answer_payload(message)
    parsed = extracted["parsed"]
    validation = validate_scores(parsed, expected_validator_ids, expected_key_kind="validator_id")
    scores = remap_scores_to_master_keys(parsed, validator_id_map)
    score_stats = compute_score_stats(scores, expected_master_keys)
    reasoning_text = extract_reasoning_text(message)
    raw_content = normalize_text_blob(message.get("content")) if isinstance(message, dict) else ""

    return {
        "model": RUNPOD_MODEL_ID,
        "backend": "runpod-sglang",
        "endpoint_id": os.environ.get("RUNPOD_ENDPOINT_ID"),
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "finish_reason": finish_reason,
        "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
        "completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
        "total_tokens": usage.get("total_tokens") if isinstance(usage, dict) else None,
        "json_valid": parsed is not None,
        "complete_result": validation.get("complete_result") if validation else False,
        "validator_count": validation.get("returned_validator_count") if validation else 0,
        "validation": validation,
        "score_stats": score_stats,
        "scores_by_validator_id": parsed,
        "scores": scores,
        "reasoning_text": reasoning_text,
        "raw_response": raw_content or "",
        "validator_id_map": validator_id_map,
    }


def print_summary(result: dict) -> None:
    if "error" in result:
        print(f"\nFAILED: {result['error']}")
        return

    stats = result.get("score_stats") or {}
    validation = result.get("validation") or {}
    count = result.get("validator_count", 0)
    expected = validation.get("expected_validator_count", "?")

    print(f"\n{'=' * 60}")
    print(f"Validators scored: {count}/{expected}")
    print(f"JSON valid: {result.get('json_valid')}")
    print(f"Complete result: {result.get('complete_result')}")
    print(f"Time: {result.get('elapsed_seconds')}s")

    if stats:
        print(f"Score range: {stats['min']} - {stats['max']} (mean {stats['mean']})")

    if validation.get("missing_keys"):
        print(f"Missing validators: {validation['missing_keys']}")
    if validation.get("invalid_score_keys"):
        print(f"Invalid scores: {validation['invalid_score_keys']}")

    if result.get("complete_result"):
        print(f"\n--- RUNPOD VALIDATION: PASS ---")
    elif result.get("json_valid"):
        print(f"\n--- RUNPOD VALIDATION: PARTIAL ---")
    else:
        print(f"\n--- RUNPOD VALIDATION: FAIL ---")
    print(f"{'=' * 60}")


def main() -> int:
    system_prompt, user_template = load_prompt_template()
    snapshot = load_snapshot()
    prompt_validators, validator_id_map = build_validator_prompt_data(snapshot["validators"])

    messages = build_messages(
        system_prompt, user_template, prompt_validators, snapshot.get("network_topology", {})
    )

    client = get_runpod_client()
    result = run_scoring(client, messages, validator_id_map)

    print_summary(result)

    output_dir = RESULTS_DIR / "runpod"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = output_dir / f"run_{timestamp}.json"
    output_path.write_text(json.dumps(result, indent=2))
    print(f"\nResult saved to {output_path}")

    return 0 if result.get("complete_result") else 1


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    sys.exit(main())
