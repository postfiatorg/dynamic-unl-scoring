"""Query any OpenAI-compatible endpoint (Modal, RunPod, local SGLang).

Usage:
    python scripts/query.py --url http://host:8000/v1 --prompt "Hello"
    python scripts/query.py --url http://host:8000/v1 --model my-model --prompt "Hello"
"""

import argparse
import sys
import time

from openai import OpenAI

DEFAULT_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0
DEFAULT_TIMEOUT = 1800


def create_client(
    base_url: str, api_key: str = "not-needed", timeout: float = DEFAULT_TIMEOUT
) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)


def query(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    elapsed = time.time() - start

    choice = response.choices[0] if response.choices else None
    usage = response.usage

    return {
        "content": choice.message.content if choice else None,
        "finish_reason": choice.finish_reason if choice else None,
        "elapsed_seconds": round(elapsed, 2),
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "total_tokens": usage.total_tokens if usage else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query an OpenAI-compatible endpoint."
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL (e.g. http://host:8000/v1)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt", required=True,
        help="User message to send",
    )
    parser.add_argument(
        "--temperature", type=float, default=DEFAULT_TEMPERATURE,
        help=f"Temperature (default: {DEFAULT_TEMPERATURE})",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
        help=f"Max tokens (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    client = create_client(args.url, timeout=args.timeout)
    messages = [{"role": "user", "content": args.prompt}]

    try:
        result = query(client, args.model, messages, args.temperature, args.max_tokens)
        print(f"\nResponse: {result['content']}")
        print(f"Time: {result['elapsed_seconds']}s")
        print(f"Tokens: {result['prompt_tokens']} in / {result['completion_tokens']} out")
        print(f"Finish reason: {result['finish_reason']}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
