"""Query any OpenAI-compatible endpoint (Modal, RunPod, local SGLang).

Usage:
    python scripts/query.py --url http://host:8000/v1 --prompt "Hello"
    python scripts/query.py --url http://host:8000/v1 --model my-model --prompt "Hello"
    python scripts/query.py --url http://host:8000/v1 --model my-model --enable-thinking --prompt "Hello"
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "Qwen/Qwen3.6-27B-FP8"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0
DEFAULT_TIMEOUT = 1800
QWEN_NONTHINKING_TEMPERATURE = 0.7
QWEN_NONTHINKING_TOP_P = 0.8
QWEN_NONTHINKING_TOP_K = 20
QWEN_NONTHINKING_PRESENCE_PENALTY = 1.5


def _load_local_env(env_file: Path = REPO_ROOT / ".env") -> None:
    load_dotenv(env_file)


def _modal_proxy_headers_from_env() -> dict[str, str] | None:
    modal_key = os.environ.get("MODAL_KEY", "").strip()
    modal_secret = os.environ.get("MODAL_SECRET", "").strip()
    if not modal_key and not modal_secret:
        return None
    if not modal_key or not modal_secret:
        raise ValueError("MODAL_KEY and MODAL_SECRET must be set together")
    return {
        "Modal-Key": modal_key,
        "Modal-Secret": modal_secret,
    }


def create_client(
    base_url: str,
    api_key: str = "not-needed",
    timeout: float = DEFAULT_TIMEOUT,
    env_file: Path | None = REPO_ROOT / ".env",
) -> OpenAI:
    if env_file is not None:
        _load_local_env(env_file)
    default_headers = _modal_proxy_headers_from_env()
    if default_headers is None:
        return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers=default_headers,
        timeout=timeout,
    )


def query(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    top_p: float | None = None,
    top_k: int | None = None,
    presence_penalty: float | None = None,
    enable_thinking: bool = False,
) -> dict:
    request_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    extra_body = {}
    if top_p is not None:
        request_kwargs["top_p"] = top_p
    if presence_penalty is not None:
        request_kwargs["presence_penalty"] = presence_penalty
    if top_k is not None:
        extra_body["top_k"] = top_k
    if not enable_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
    if extra_body:
        request_kwargs["extra_body"] = extra_body

    start = time.time()
    response = client.chat.completions.create(**request_kwargs)
    elapsed = time.time() - start

    choice = response.choices[0] if response.choices else None
    usage = response.usage
    message = choice.message if choice else None
    reasoning_content = getattr(message, "reasoning_content", None)
    reasoning = getattr(message, "reasoning", None)

    return {
        "content": message.content if message else None,
        "reasoning_content": reasoning_content or reasoning,
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
        "--top-p",
        type=float,
        help="Nucleus sampling top_p value.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        help="Top-k sampling value passed in extra_body.",
    )
    parser.add_argument(
        "--presence-penalty",
        type=float,
        help="Presence penalty.",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
        help=f"Max tokens (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--enable-thinking",
        dest="enable_thinking",
        action="store_true",
        help="Allow Qwen thinking output. Non-thinking mode is the default.",
    )
    parser.add_argument(
        "--qwen-nonthinking-defaults",
        action="store_true",
        help="Use Qwen's recommended non-thinking sampling defaults.",
    )
    parser.set_defaults(enable_thinking=False)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    client = create_client(args.url, timeout=args.timeout)
    messages = [{"role": "user", "content": args.prompt}]
    temperature = args.temperature
    top_p = args.top_p
    top_k = args.top_k
    presence_penalty = args.presence_penalty
    enable_thinking = args.enable_thinking

    if args.qwen_nonthinking_defaults:
        temperature = QWEN_NONTHINKING_TEMPERATURE
        top_p = QWEN_NONTHINKING_TOP_P if top_p is None else top_p
        top_k = QWEN_NONTHINKING_TOP_K if top_k is None else top_k
        presence_penalty = (
            QWEN_NONTHINKING_PRESENCE_PENALTY
            if presence_penalty is None
            else presence_penalty
        )
        enable_thinking = False

    try:
        result = query(
            client,
            args.model,
            messages,
            temperature,
            args.max_tokens,
            top_p,
            top_k,
            presence_penalty,
            enable_thinking,
        )
        print(f"\nResponse: {result['content']}")
        if result["reasoning_content"] and not result["content"]:
            print(f"Reasoning content: {result['reasoning_content']}")
        print(f"Time: {result['elapsed_seconds']}s")
        print(f"Tokens: {result['prompt_tokens']} in / {result['completion_tokens']} out")
        print(f"Finish reason: {result['finish_reason']}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
