"""Round 2 model benchmark: smaller models that fit on a single H200/B200."""

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
        "name": "qwen3-next-80b-thinking",
        "model_id": "qwen/qwen3-next-80b-a3b-thinking",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {"reasoning": {"effort": "high"}},
        "response_format": None,
    },
    {
        "name": "qwen3-next-80b-instruct",
        "model_id": "qwen/qwen3-next-80b-a3b-instruct",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    },
    {
        "name": "qwen3-32b",
        "model_id": "qwen/qwen3-32b",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    },
    {
        "name": "gpt-oss-120b",
        "model_id": "openai/gpt-oss-120b",
        "params": {"temperature": 0, "max_tokens": DEFAULT_MAX_TOKENS},
        "extra_body": {},
        "response_format": JSON_RESPONSE_FORMAT,
    },
]


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    sys.exit(run_benchmark(parse_args(), MODELS, RESULTS_DIR))
