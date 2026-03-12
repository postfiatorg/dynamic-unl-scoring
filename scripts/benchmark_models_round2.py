"""Round 2 model benchmark: smaller models that fit on a single H200/B200."""

import sys

from benchmark_models import (
    DEFAULT_MAX_TOKENS,
    JSON_RESPONSE_FORMAT,
    REPO_ROOT,
    parse_args,
    run_benchmark,
    select_models,
)

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


def _patched_select_models(requested_models):
    """select_models bound to this file's MODELS list."""
    if not requested_models:
        return MODELS

    available = {m["name"]: m for m in MODELS}
    missing = [n for n in requested_models if n not in available]
    if missing:
        raise ValueError(
            f"Unknown model(s): {', '.join(missing)}. "
            f"Available: {', '.join(sorted(available))}"
        )
    return [available[n] for n in requested_models]


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    import benchmark_models

    benchmark_models.select_models = _patched_select_models
    sys.exit(run_benchmark(parse_args()))
