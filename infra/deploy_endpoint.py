"""Deploy an LLM on Modal with SGLang for Dynamic UNL scoring.

See docs/phase0/DeployQwen80B.md for deployment details and tuning rationale.

Usage:
    modal run infra/deploy_endpoint.py      # Ephemeral test run
    modal deploy infra/deploy_endpoint.py   # Persistent deployment

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

MODEL_ID = os.environ.get("SCORING_MODEL_ID", "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")
GPU_TYPE = os.environ.get("SCORING_GPU_TYPE", "H200")
QUANTIZATION = os.environ.get("SCORING_QUANTIZATION", "fp8")
ATTENTION_BACKEND = os.environ.get("SCORING_ATTENTION_BACKEND", "")
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

SGLANG_PORT = 8000
MINUTES = 60
SGLANG_IMAGE_TAG = "lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime"
HF_CACHE_PATH = "/root/.cache/huggingface"
# Override Qwen3's default 512 MB FlashInfer workspace to 2 GB.
# Without this, the ~8K-token scoring prompt OOMs during attention computation.
FLASHINFER_WORKSPACE_BYTES = "2147483648"

app = modal.App(name="dynamic-unl-scoring")

# --- Image build (runs once at deploy time, cached afterwards) ---

sglang_image = (
    modal.Image.from_registry(SGLANG_IMAGE_TAG)
    .entrypoint([])
    .pip_install("huggingface_hub[hf_transfer]")
    .env({
        "HF_HUB_CACHE": HF_CACHE_PATH,
        "HF_XET_HIGH_PERFORMANCE": "1",
        "SGLANG_FLASHINFER_WORKSPACE_SIZE": FLASHINFER_WORKSPACE_BYTES,
    })
)

model_volume = modal.Volume.from_name("scoring-model-weights", create_if_missing=True)


# Bake model weights into the image so they aren't downloaded on every cold start.
def download_model(repo_id: str):
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=repo_id)


sglang_image = sglang_image.run_function(
    download_model,
    volumes={HF_CACHE_PATH: model_volume},
    args=(MODEL_ID,),
)

# Pre-compile DeepGEMM kernels on an H200 during build.
# Without this, compilation happens on first cold start (~15 min → ~2 min).
sglang_image = sglang_image.run_commands(
    [
        f"python3 -m sglang.compile_deep_gemm "
        f"--model {MODEL_ID} --tp {TENSOR_PARALLEL} --trust-remote-code"
    ],
    gpu="H200",
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
        cmd = [
            "python", "-m", "sglang.launch_server",
            "--model-path", MODEL_ID,
            "--served-model-name", MODEL_ID,
            "--host", "0.0.0.0",
            "--port", str(SGLANG_PORT),
            "--tp", str(TENSOR_PARALLEL),
            "--mem-fraction-static", str(MEM_FRACTION_STATIC),
            "--chunked-prefill-size", str(CHUNKED_PREFILL_SIZE),
            "--max-running-requests", str(MAX_RUNNING_REQUESTS),
            "--enable-deterministic-inference",
            "--enable-metrics",
        ]
        if QUANTIZATION:
            cmd += ["--quantization", QUANTIZATION]
        if ATTENTION_BACKEND:
            cmd += ["--attention-backend", ATTENTION_BACKEND]
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
