"""Run the scoring prompt against candidate models via OpenRouter and save results."""

import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "scoring_v1.txt"
SNAPSHOT_PATH = REPO_ROOT / "data" / "testnet_snapshot.json"
RESULTS_DIR = REPO_ROOT / "results"
RUNS_PER_MODEL = 5

MODELS = [
    {
        "name": "qwen3-235b-thinking",
        "model_id": "qwen/qwen3-235b-a22b",
        "params": {"temperature": 0},
    },
    {
        "name": "qwen3-235b-instruct",
        "model_id": "qwen/qwen3-235b-a22b:instruct",
        "params": {"temperature": 0},
    },
    {
        "name": "minimax-m2.5",
        "model_id": "minimax/minimax-m2.5",
        "params": {"temperature": 0},
    },
]


def load_prompt_template() -> tuple[str, str]:
    raw = PROMPT_PATH.read_text()
    parts = raw.split("### USER PROMPT ###")
    system_prompt = parts[0].replace("### SYSTEM PROMPT ###", "").strip()
    user_prompt_template = parts[1].strip()
    return system_prompt, user_prompt_template


def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text())


def build_messages(system_prompt: str, user_template: str, snapshot: dict) -> list:
    validator_json = json.dumps(snapshot["validators"], indent=2)
    user_content = user_template.replace("{validator_data}", validator_json)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def extract_json_from_response(text: str) -> dict | None:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def run_single(
    client: OpenAI, model_cfg: dict, messages: list, run_num: int
) -> dict:
    model_name = model_cfg["name"]
    model_id = model_cfg["model_id"]
    print(f"  Run {run_num}/{RUNS_PER_MODEL} for {model_name}...")

    start = time.time()
    response = client.chat.completions.create(
        model=model_id,
        messages=messages,
        response_format={"type": "json_object"},
        **model_cfg["params"],
    )
    elapsed = time.time() - start

    raw_content = response.choices[0].message.content or ""
    parsed = extract_json_from_response(raw_content)

    usage = response.usage
    result = {
        "model": model_id,
        "model_name": model_name,
        "run": run_num,
        "elapsed_seconds": round(elapsed, 2),
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "total_tokens": usage.total_tokens if usage else None,
        "json_valid": parsed is not None,
        "validator_count": len(parsed) if parsed else 0,
        "raw_response": raw_content,
        "scores": parsed,
    }

    if parsed:
        scores = [
            v["score"] for v in parsed.values() if isinstance(v, dict) and "score" in v
        ]
        if scores:
            result["score_stats"] = {
                "min": min(scores),
                "max": max(scores),
                "mean": round(sum(scores) / len(scores), 2),
                "spread": max(scores) - min(scores),
            }

    return result


def run_benchmark():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in.")
        return 1

    if not SNAPSHOT_PATH.exists():
        print(f"Error: No snapshot at {SNAPSHOT_PATH}. Run fetch_vhs_data.py first.")
        return 1

    system_prompt, user_template = load_prompt_template()
    snapshot = load_snapshot()
    print(f"Loaded snapshot with {snapshot['validator_count']} validators")

    messages = build_messages(system_prompt, user_template, snapshot)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        model_dir = RESULTS_DIR / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nBenchmarking {model_name} ({model_cfg['model_id']})")

        for run_num in range(1, RUNS_PER_MODEL + 1):
            result = run_single(client, model_cfg, messages, run_num)
            output_path = model_dir / f"run_{run_num}.json"
            output_path.write_text(json.dumps(result, indent=2))

            status = "valid JSON" if result["json_valid"] else "INVALID JSON"
            validators = result["validator_count"]
            elapsed = result["elapsed_seconds"]
            stats = result.get("score_stats", {})
            score_info = (
                f", scores {stats['min']}-{stats['max']} (mean {stats['mean']})"
                if stats
                else ""
            )
            print(f"    {status}, {validators} validators, {elapsed}s{score_info}")

    print(f"\nAll results saved to {RESULTS_DIR}/")
    return 0


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    sys.exit(run_benchmark())
