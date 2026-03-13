"""Shared scoring utilities for benchmarks and production scoring."""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "scoring_v1.txt"
SNAPSHOT_PATH = REPO_ROOT / "data" / "testnet_snapshot.json"
DEFAULT_RUNS_PER_MODEL = 5
DEFAULT_MAX_TOKENS = 16384
DEFAULT_SESSION_TIME_FORMAT = "%Y-%m-%d_%H-%M-%S"
JSON_RESPONSE_FORMAT = {"type": "json_object"}
KEY_FIELDS = {"master_key", "signing_key"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark candidate models against the validator scoring prompt."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS_PER_MODEL,
        help=f"Runs per model (default: {DEFAULT_RUNS_PER_MODEL})",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Benchmark only the named model. Can be passed multiple times.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing run_N.json files instead of skipping them.",
    )
    parser.add_argument(
        "--session-name",
        help=(
            "Results subdirectory name under results/. "
            "Default: current local timestamp like 2026-03-10_14-30-00."
        ),
    )
    return parser.parse_args()


def load_prompt_template() -> tuple[str, str]:
    raw = PROMPT_PATH.read_text()
    parts = raw.split("### USER PROMPT ###")
    if len(parts) != 2:
        raise ValueError(
            f"Prompt template at {PROMPT_PATH} must contain exactly one USER PROMPT marker."
        )

    system_prompt = parts[0].replace("### SYSTEM PROMPT ###", "").strip()
    user_prompt_template = parts[1].strip()
    return system_prompt, user_prompt_template


def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text())


def safe_json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def to_serializable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [to_serializable(item) for item in value]

    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_serializable(model_dump(mode="json"))

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        return to_serializable(dict_method())

    return str(value)


def build_validator_prompt_data(validators: list[dict]) -> tuple[list[dict], dict[str, str]]:
    prompt_validators = []
    validator_id_map = {}

    for index, validator in enumerate(validators, start=1):
        validator_id = f"v{index:03d}"
        validator_id_map[validator_id] = validator["master_key"]

        prompt_entry = {"validator_id": validator_id}
        for key, value in validator.items():
            if key not in KEY_FIELDS:
                prompt_entry[key] = value

        prompt_validators.append(prompt_entry)

    return prompt_validators, validator_id_map


def build_messages(
    system_prompt: str, user_template: str, prompt_validators: list[dict], topology: dict
) -> list:
    validator_json = safe_json_dumps(prompt_validators)
    topology_json = safe_json_dumps(topology)
    user_content = user_template.replace("{validator_data}", validator_json)
    user_content = user_content.replace("{topology_data}", topology_json)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def normalize_text_blob(value: object) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)

    if isinstance(value, dict):
        for key in ("text", "content", "reasoning_content", "reasoning"):
            if key in value:
                text = normalize_text_blob(value[key])
                if text:
                    return text
        return None

    if isinstance(value, list):
        parts = []
        for item in value:
            text = normalize_text_blob(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip() or None

    return None


def extract_json_from_response(text: str) -> dict | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    return None


def build_answer_candidates(message_payload: dict | None) -> list[tuple[str, str]]:
    if not isinstance(message_payload, dict):
        return []

    candidates = []
    for field in ("parsed",):
        value = message_payload.get(field)
        if isinstance(value, (dict, list)):
            candidates.append((f"message.{field}", safe_json_dumps(value)))

    for field in ("content", "output_text", "text", "answer"):
        text = normalize_text_blob(message_payload.get(field))
        if text:
            candidates.append((f"message.{field}", text))

    deduped = []
    seen = set()
    for source, text in candidates:
        if text not in seen:
            seen.add(text)
            deduped.append((source, text))
    return deduped


def extract_reasoning_text(message_payload: dict | None) -> str | None:
    if not isinstance(message_payload, dict):
        return None

    for field in ("reasoning_content", "reasoning"):
        text = normalize_text_blob(message_payload.get(field))
        if text:
            return text

    return None


def extract_answer_payload(message_payload: dict | None) -> dict:
    candidates = build_answer_candidates(message_payload)
    first_source = candidates[0][0] if candidates else None
    first_text = candidates[0][1] if candidates else ""

    for source, text in candidates:
        parsed = extract_json_from_response(text)
        if parsed is not None:
            return {
                "parsed": parsed,
                "answer_text": text,
                "answer_source": source,
                "candidate_sources": [candidate_source for candidate_source, _ in candidates],
            }

    return {
        "parsed": None,
        "answer_text": first_text,
        "answer_source": first_source,
        "candidate_sources": [candidate_source for candidate_source, _ in candidates],
    }


def normalize_score(value: object) -> int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        score = value
    elif isinstance(value, float) and value.is_integer():
        score = int(value)
    else:
        return None

    return score if 0 <= score <= 100 else None


def remap_validator_ids_to_master_keys(
    validator_ids: list[str], validator_id_map: dict[str, str]
) -> list[str]:
    return [validator_id_map[validator_id] for validator_id in validator_ids if validator_id in validator_id_map]


def remap_scores_to_master_keys(
    parsed: dict | None, validator_id_map: dict[str, str]
) -> dict | None:
    if not isinstance(parsed, dict):
        return None

    remapped = {}
    for validator_id, entry in parsed.items():
        master_key = validator_id_map.get(validator_id)
        if master_key is not None:
            remapped[master_key] = entry

    return remapped


def validate_scores(
    parsed: dict | None, expected_keys: list[str], expected_key_kind: str = "key"
) -> dict | None:
    if not isinstance(parsed, dict):
        return None

    expected = set(expected_keys)
    actual = set(parsed)

    missing_keys = sorted(expected - actual)
    unexpected_keys = sorted(actual - expected)
    invalid_structure_keys = []
    invalid_score_keys = []
    invalid_reasoning_keys = []
    valid_score_count = 0

    for key in sorted(expected & actual):
        entry = parsed.get(key)
        if not isinstance(entry, dict):
            invalid_structure_keys.append(key)
            continue

        if normalize_score(entry.get("score")) is None:
            invalid_score_keys.append(key)
        else:
            valid_score_count += 1

        reasoning = entry.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            invalid_reasoning_keys.append(key)

    complete_result = (
        not missing_keys
        and not invalid_structure_keys
        and not invalid_score_keys
        and not invalid_reasoning_keys
    )
    strict_match = complete_result and not unexpected_keys

    return {
        "expected_key_kind": expected_key_kind,
        "expected_validator_count": len(expected_keys),
        "returned_validator_count": len(parsed),
        "valid_score_count": valid_score_count,
        "missing_keys": missing_keys,
        "unexpected_keys": unexpected_keys,
        "invalid_structure_keys": invalid_structure_keys,
        "invalid_score_keys": invalid_score_keys,
        "invalid_reasoning_keys": invalid_reasoning_keys,
        "usable_result": complete_result,
        "complete_result": complete_result,
        "strict_match": strict_match,
    }


def compute_score_stats(parsed: dict | None, expected_keys: list[str]) -> dict | None:
    if not isinstance(parsed, dict):
        return None

    scores = []
    for key in expected_keys:
        entry = parsed.get(key)
        if isinstance(entry, dict):
            score = normalize_score(entry.get("score"))
            if score is not None:
                scores.append(score)

    if not scores:
        return None

    return {
        "min": min(scores),
        "max": max(scores),
        "mean": round(sum(scores) / len(scores), 2),
        "spread": max(scores) - min(scores),
    }


def build_result_summary(result: dict) -> str:
    validation = result.get("validation") or {}
    expected_count = validation.get("expected_validator_count", "?")
    returned_count = validation.get("returned_validator_count", result.get("validator_count", 0))
    elapsed = result.get("elapsed_seconds", 0)

    if result.get("complete_result"):
        status = "COMPLETE"
    elif result.get("json_valid"):
        status = "PARTIAL JSON"
    else:
        status = "INVALID JSON"

    details = []
    if validation.get("missing_keys"):
        details.append(f"{len(validation['missing_keys'])} missing")
    if validation.get("unexpected_keys"):
        details.append(f"{len(validation['unexpected_keys'])} unexpected")
    if validation.get("invalid_score_keys"):
        details.append(f"{len(validation['invalid_score_keys'])} bad scores")
    if validation.get("invalid_reasoning_keys"):
        details.append(f"{len(validation['invalid_reasoning_keys'])} bad reasoning")

    stats = result.get("score_stats", {})
    score_info = (
        f", scores {stats['min']}-{stats['max']} (mean {stats['mean']})"
        if stats
        else ""
    )
    detail_info = f", {', '.join(details)}" if details else ""
    return f"{status}, {returned_count}/{expected_count} validators, {elapsed}s{score_info}{detail_info}"


def run_single(
    client: OpenAI,
    model_cfg: dict,
    messages: list,
    run_num: int,
    validator_id_map: dict[str, str],
) -> dict:
    model_name = model_cfg["name"]
    model_id = model_cfg["model_id"]
    print(f"  Run {run_num} for {model_name}...")
    expected_validator_ids = list(validator_id_map)
    expected_master_keys = [validator_id_map[validator_id] for validator_id in expected_validator_ids]

    request_kwargs = {
        "model": model_id,
        "messages": messages,
        "extra_body": model_cfg.get("extra_body", {}),
        **model_cfg["params"],
    }
    if model_cfg.get("response_format") is not None:
        request_kwargs["response_format"] = model_cfg["response_format"]

    start = time.time()
    try:
        response = client.chat.completions.create(**request_kwargs)
        elapsed = time.time() - start
    except Exception as exc:
        elapsed = time.time() - start
        print(f"    API error: {exc}")
        return {
            "model": model_id,
            "model_name": model_name,
            "run": run_num,
            "elapsed_seconds": round(elapsed, 2),
            "request_config": {
                "params": model_cfg["params"],
                "extra_body": model_cfg.get("extra_body", {}),
                "response_format": model_cfg.get("response_format"),
            },
            "finish_reason": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "json_valid": False,
            "usable_result": False,
            "complete_result": False,
            "validator_count": 0,
            "raw_response": "",
            "extracted_answer_text": "",
            "extracted_answer_source": None,
            "reasoning_text": None,
            "candidate_answer_sources": [],
            "validation": None,
            "validator_id_map": validator_id_map,
            "scores_by_validator_id": None,
            "message_payload": None,
            "scores": None,
            "score_stats": None,
            "error": str(exc),
        }

    response_payload = to_serializable(response)
    usage_payload = response_payload.get("usage") if isinstance(response_payload, dict) else None
    choices_payload = response_payload.get("choices") if isinstance(response_payload, dict) else None
    choice_payload = choices_payload[0] if choices_payload else {}
    message_payload = choice_payload.get("message") if isinstance(choice_payload, dict) else None
    finish_reason = choice_payload.get("finish_reason") if isinstance(choice_payload, dict) else None

    extracted = extract_answer_payload(message_payload)
    parsed = extracted["parsed"]
    validation = validate_scores(parsed, expected_validator_ids, expected_key_kind="validator_id")
    if validation is not None:
        validation["missing_master_keys"] = remap_validator_ids_to_master_keys(
            validation["missing_keys"], validator_id_map
        )
    scores = remap_scores_to_master_keys(parsed, validator_id_map)
    score_stats = compute_score_stats(scores, expected_master_keys)
    raw_content = normalize_text_blob(message_payload.get("content")) if isinstance(message_payload, dict) else ""
    reasoning_text = extract_reasoning_text(message_payload)

    result = {
        "model": model_id,
        "model_name": model_name,
        "run": run_num,
        "elapsed_seconds": round(elapsed, 2),
        "request_config": {
            "params": model_cfg["params"],
            "extra_body": model_cfg.get("extra_body", {}),
            "response_format": model_cfg.get("response_format"),
        },
        "finish_reason": finish_reason,
        "prompt_tokens": usage_payload.get("prompt_tokens") if isinstance(usage_payload, dict) else None,
        "completion_tokens": usage_payload.get("completion_tokens") if isinstance(usage_payload, dict) else None,
        "total_tokens": usage_payload.get("total_tokens") if isinstance(usage_payload, dict) else None,
        "json_valid": parsed is not None,
        "usable_result": validation.get("usable_result") if validation else False,
        "complete_result": validation.get("complete_result") if validation else False,
        "validator_count": validation.get("returned_validator_count") if validation else 0,
        "raw_response": raw_content or "",
        "extracted_answer_text": extracted["answer_text"],
        "extracted_answer_source": extracted["answer_source"],
        "reasoning_text": reasoning_text,
        "candidate_answer_sources": extracted["candidate_sources"],
        "validation": validation,
        "validator_id_map": validator_id_map,
        "scores_by_validator_id": parsed,
        "message_payload": message_payload,
        "scores": scores,
        "score_stats": score_stats,
    }

    return result


def load_result(path: Path) -> dict:
    return json.loads(path.read_text())


def build_session_name() -> str:
    return datetime.now().strftime(DEFAULT_SESSION_TIME_FORMAT)


def select_models(requested_models: list[str] | None, available_models: list[dict]) -> list[dict]:
    if not requested_models:
        return available_models

    available = {model["name"]: model for model in available_models}
    missing = [name for name in requested_models if name not in available]
    if missing:
        raise ValueError(
            f"Unknown model(s): {', '.join(missing)}. Available: {', '.join(sorted(available))}"
        )

    return [available[name] for name in requested_models]


def run_benchmark(args: argparse.Namespace, models: list[dict], results_dir: Path) -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in.")
        return 1

    if not SNAPSHOT_PATH.exists():
        print(f"Error: No snapshot at {SNAPSHOT_PATH}. Run fetch_vhs_data.py first.")
        return 1

    if args.runs < 1:
        print("Error: --runs must be >= 1.")
        return 1

    system_prompt, user_template = load_prompt_template()
    snapshot = load_snapshot()
    prompt_validators, validator_id_map = build_validator_prompt_data(snapshot["validators"])
    session_name = args.session_name or build_session_name()
    session_dir = results_dir / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"Loaded snapshot with {snapshot['validator_count']} validators")
    print(f"Saving results to {session_dir}")

    messages = build_messages(
        system_prompt,
        user_template,
        prompt_validators,
        snapshot.get("network_topology", {}),
    )
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    for model_cfg in select_models(args.models, models):
        model_name = model_cfg["name"]
        model_dir = session_dir / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nBenchmarking {model_name} ({model_cfg['model_id']})")

        for run_num in range(1, args.runs + 1):
            output_path = model_dir / f"run_{run_num}.json"
            if output_path.exists() and not args.force:
                existing = load_result(output_path)
                print(
                    f"    Skipping existing {output_path.name}: {build_result_summary(existing)}"
                )
                continue

            result = run_single(client, model_cfg, messages, run_num, validator_id_map)
            output_path.write_text(json.dumps(result, indent=2))
            print(f"    {build_result_summary(result)}")

    print(f"\nAll results saved to {session_dir}/")
    return 0
