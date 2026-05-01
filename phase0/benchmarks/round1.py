"""Round 1 model benchmark: large models via OpenRouter."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scoring_utils import (
    DEFAULT_MAX_TOKENS,
    JSON_RESPONSE_FORMAT,
    parse_args,
    run_benchmark,
)

RESULTS_DIR = REPO_ROOT / "phase0" / "benchmarks" / "results"

MODELS = [
    {
        "name": "qwen3-235b-thinking",
        "model_id": "qwen/qwen3-235b-a22b",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {"reasoning": {"effort": "high"}},
        "response_format": None,
    },
    {
        "name": "qwen3-235b-instruct",
        "model_id": "qwen/qwen3-235b-a22b",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {"reasoning": {"effort": "none"}},
        "response_format": JSON_RESPONSE_FORMAT,
    },
    {
        "name": "minimax-m2.5",
        "model_id": "minimax/minimax-m2.5",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    },
    {
        "name": "qwen3-235b-thinking-2507",
        "model_id": "qwen/qwen3-235b-a22b-thinking-2507",
        "params": {"temperature": 0, "max_tokens": 65536},
        "extra_body": {},
        "response_format": None,
    },
]


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    sys.exit(run_benchmark(parse_args(), MODELS, RESULTS_DIR))
