"""Shared Modal/SGLang deployment implementation for Dynamic UNL scoring.

Do not run this file directly for normal model deployments. Use a model-specific
wrapper that sets explicit defaults before importing this module:

    modal run infra/deploy_qwen3_next_endpoint.py
    modal run infra/deploy_qwen36_endpoint.py

Timing:
    First deploy (image build + DeepGEMM compilation): ~18 minutes
    Subsequent deploys (cached image, config-only changes): ~3 seconds
    Cold start per container (weight loading + CUDA graphs): ~5 minutes
"""

import os
import subprocess
import time

import modal

# --- Configuration ---

APP_NAME = os.environ.get("SCORING_APP_NAME", "dynamic-unl-scoring")
MODEL_ID = os.environ.get("SCORING_MODEL_ID", "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")
GPU_TYPE = os.environ.get("SCORING_GPU_TYPE", "H200")
QUANTIZATION = os.environ.get("SCORING_QUANTIZATION", "fp8")
ATTENTION_BACKEND = os.environ.get("SCORING_ATTENTION_BACKEND", "")
REASONING_PARSER = os.environ.get("SCORING_REASONING_PARSER", "")
TENSOR_PARALLEL = int(os.environ.get("SCORING_TP", "1"))
# Share of GPU memory reserved for model weights and KV cache (0.75 = 75%).
# Lower than default 0.90 to leave room for Qwen3-Next's ~36 GB Mamba state cache.
MEM_FRACTION_STATIC = float(os.environ.get("SCORING_MEM_FRACTION", "0.75"))
# Process input tokens in chunks of this size instead of all at once.
# Keeps peak memory stable for the ~8K-token scoring prompt.
CHUNKED_PREFILL_SIZE = int(os.environ.get("SCORING_CHUNKED_PREFILL", "4096"))
# Max concurrent requests the server will handle.
# Low value prevents OOM when each request allocates its own temporary GPU state.
MAX_RUNNING_REQUESTS = int(os.environ.get("SCORING_MAX_REQS", "4"))
PRELOAD_MODEL = os.environ.get("SCORING_PRELOAD_MODEL", "1") != "0"
COMPILE_DEEPGEMM = os.environ.get("SCORING_COMPILE_DEEPGEMM", "1") != "0"
COMPILE_GPU_TYPE = os.environ.get("SCORING_COMPILE_GPU_TYPE", GPU_TYPE)

SGLANG_PORT = 8000
MINUTES = 60
SGLANG_IMAGE_TAG = os.environ.get(
    "SCORING_SGLANG_IMAGE_TAG",
    "lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime",
)
HF_CACHE_PATH = "/model-cache/huggingface"
MODEL_VOLUME_NAME = os.environ.get("SCORING_MODEL_VOLUME", "scoring-model-weights")
# Override Qwen3's default 512 MB FlashInfer workspace to 2 GB.
# Without this, the ~8K-token scoring prompt OOMs during attention computation.
FLASHINFER_WORKSPACE_BYTES = "2147483648"
RUNTIME_ENV = {
    "HF_HOME": HF_CACHE_PATH,
    "HF_HUB_CACHE": HF_CACHE_PATH,
    "HF_XET_HIGH_PERFORMANCE": "1",
    "SGLANG_FLASHINFER_WORKSPACE_SIZE": FLASHINFER_WORKSPACE_BYTES,
    "SCORING_APP_NAME": APP_NAME,
    "SCORING_MODEL_ID": MODEL_ID,
    "SCORING_GPU_TYPE": GPU_TYPE,
    "SCORING_QUANTIZATION": QUANTIZATION,
    "SCORING_ATTENTION_BACKEND": ATTENTION_BACKEND,
    "SCORING_REASONING_PARSER": REASONING_PARSER,
    "SCORING_TP": str(TENSOR_PARALLEL),
    "SCORING_MEM_FRACTION": str(MEM_FRACTION_STATIC),
    "SCORING_CHUNKED_PREFILL": str(CHUNKED_PREFILL_SIZE),
    "SCORING_MAX_REQS": str(MAX_RUNNING_REQUESTS),
    "SCORING_PRELOAD_MODEL": "1" if PRELOAD_MODEL else "0",
    "SCORING_COMPILE_DEEPGEMM": "1" if COMPILE_DEEPGEMM else "0",
    "SCORING_COMPILE_GPU_TYPE": COMPILE_GPU_TYPE,
    "SCORING_SGLANG_IMAGE_TAG": SGLANG_IMAGE_TAG,
    "SCORING_MODEL_VOLUME": MODEL_VOLUME_NAME,
}

app = modal.App(name=APP_NAME)

# --- Image build (runs once at deploy time, cached afterwards) ---

sglang_image = (
    modal.Image.from_registry(SGLANG_IMAGE_TAG)
    .entrypoint([])
    .pip_install("huggingface_hub", "hf_xet")
    .env(RUNTIME_ENV)
)

model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)


def find_cached_snapshot(repo_id: str) -> str | None:
    from pathlib import Path

    repo_cache_name = "models--" + repo_id.replace("/", "--")
    snapshots_dir = Path(HF_CACHE_PATH) / repo_cache_name / "snapshots"
    if not snapshots_dir.exists():
        return None

    for snapshot_dir in snapshots_dir.iterdir():
        if snapshot_dir.is_dir() and any(snapshot_dir.glob("*.safetensors")):
            return str(snapshot_dir)
    return None


# Cache model weights in the Modal volume so they are not downloaded on each cold start.
def download_model(repo_id: str):
    import traceback

    from huggingface_hub import snapshot_download

    cached_snapshot = find_cached_snapshot(repo_id)
    if cached_snapshot:
        print(f"Found cached Hugging Face snapshot for {repo_id}: {cached_snapshot}", flush=True)
        return

    print(f"Downloading Hugging Face snapshot for {repo_id}", flush=True)
    try:
        snapshot_path = snapshot_download(repo_id=repo_id)
    except Exception:
        print(f"Failed to download Hugging Face snapshot for {repo_id}", flush=True)
        traceback.print_exc()
        cached_snapshot = find_cached_snapshot(repo_id)
        if cached_snapshot:
            print(
                f"Using cached Hugging Face snapshot after download failure: {cached_snapshot}",
                flush=True,
            )
            return
        raise
    print(f"Downloaded Hugging Face snapshot for {repo_id}: {snapshot_path}", flush=True)


if PRELOAD_MODEL:
    sglang_image = sglang_image.run_function(
        download_model,
        volumes={HF_CACHE_PATH: model_volume},
        args=(MODEL_ID,),
    )

# Pre-compile DeepGEMM kernels during build. Without this, compilation can happen on
# first cold start. Compile on the same GPU type used for serving unless explicitly
# overridden.
if COMPILE_DEEPGEMM:
    sglang_image = sglang_image.run_commands(
        [
            f"python3 -m sglang.compile_deep_gemm "
            f"--model {MODEL_ID} --tp {TENSOR_PARALLEL} --trust-remote-code"
        ],
        gpu=COMPILE_GPU_TYPE,
        volumes={HF_CACHE_PATH: model_volume},
    )

with sglang_image.imports():
    import requests


def wait_for_server(timeout: int = 30 * MINUTES):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{SGLANG_PORT}/health", timeout=5)
            if resp.status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(5)
    raise TimeoutError(f"SGLang server not ready within {timeout}s")


# --- Endpoint (runs on each container start) ---

@app.cls(
    image=sglang_image,
    gpu=GPU_TYPE,
    volumes={HF_CACHE_PATH: model_volume},
    timeout=60 * MINUTES,
    scaledown_window=20 * MINUTES,
)
class ScoringEndpoint:
    @modal.enter()
    def start_server(self):
        model_id = os.environ.get("SCORING_MODEL_ID", MODEL_ID)
        quantization = os.environ.get("SCORING_QUANTIZATION", QUANTIZATION)
        attention_backend = os.environ.get("SCORING_ATTENTION_BACKEND", ATTENTION_BACKEND)
        reasoning_parser = os.environ.get("SCORING_REASONING_PARSER", REASONING_PARSER)
        tensor_parallel = int(os.environ.get("SCORING_TP", str(TENSOR_PARALLEL)))
        mem_fraction_static = float(
            os.environ.get("SCORING_MEM_FRACTION", str(MEM_FRACTION_STATIC))
        )
        chunked_prefill_size = int(
            os.environ.get("SCORING_CHUNKED_PREFILL", str(CHUNKED_PREFILL_SIZE))
        )
        max_running_requests = int(
            os.environ.get("SCORING_MAX_REQS", str(MAX_RUNNING_REQUESTS))
        )
        print(
            "Launching SGLang with "
            f"model={model_id}, quantization={quantization or 'auto'}, "
            f"tp={tensor_parallel}, mem_fraction={mem_fraction_static}, "
            f"chunked_prefill={chunked_prefill_size}, "
            f"max_running_requests={max_running_requests}",
            flush=True,
        )
        cmd = [
            "python", "-m", "sglang.launch_server",
            "--model-path", model_id,
            "--served-model-name", model_id,
            "--host", "0.0.0.0",
            "--port", str(SGLANG_PORT),
            "--tp", str(tensor_parallel),
            "--mem-fraction-static", str(mem_fraction_static),
            "--chunked-prefill-size", str(chunked_prefill_size),
            "--max-running-requests", str(max_running_requests),
            "--enable-deterministic-inference",
            "--enable-metrics",
            "--trust-remote-code",
        ]
        if quantization:
            cmd += ["--quantization", quantization]
        if attention_backend:
            cmd += ["--attention-backend", attention_backend]
        if reasoning_parser:
            cmd += ["--reasoning-parser", reasoning_parser]
        self.process = subprocess.Popen(cmd)
        wait_for_server()

    @modal.web_server(port=SGLANG_PORT, startup_timeout=35 * MINUTES)
    def serve(self):
        pass

    @modal.exit()
    def stop(self):
        self.process.terminate()


# --- Local smoke test (runs on your machine via `modal run`) ---

@app.local_entrypoint()
def smoke_test():
    import json
    import urllib.request

    url = ScoringEndpoint().serve.get_web_url()
    print(f"Endpoint URL: {url}")

    payload = json.dumps({
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "Hello, who are you?"}],
        "temperature": 0,
        "max_tokens": 64,
    }).encode()

    deadline = time.time() + 35 * MINUTES
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"{url}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            start = time.time()
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            elapsed = time.time() - start

            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            print(f"\nResponse: {content}")
            print(f"Time: {elapsed:.1f}s")
            print(
                f"Tokens: {usage.get('prompt_tokens', '?')} in"
                f" / {usage.get('completion_tokens', '?')} out"
            )
            return
        except Exception as exc:
            print(f"Waiting for server... ({type(exc).__name__})")
            time.sleep(10)

    raise TimeoutError("No response from endpoint within timeout")
