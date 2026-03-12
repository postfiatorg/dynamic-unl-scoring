"""Deploy Qwen3-235B-A22B on Modal with SGLang for Dynamic UNL scoring.

Serves the model on a single B200 GPU with deterministic inference enabled.
Uses AWQ quantization with Marlin kernels (community, QuixiAI). H200
(141 GB) is too small: both GPTQ-Int4 and AWQ OOM during the 768 MB
Marlin MoE kernel repacking step (model weights consume 138-139 GB,
leaving insufficient headroom). B200 (192 GB) provides the necessary
margin. Must explicitly pass --quantization awq_marlin to prevent SGLang
from falling back to non-Marlin AWQ which loads weights in FP16.

Usage:
    modal run infra/modal/scoring_endpoint.py      # Ephemeral test run
    modal deploy infra/modal/scoring_endpoint.py   # Persistent deployment
"""

import subprocess
import time

import modal

MINUTES = 60
SGLANG_PORT = 8000

MODEL_ID = "QuixiAI/Qwen3-235B-A22B-AWQ"
# Both GPTQ-Int4 and AWQ OOM during Marlin MoE repacking on H200 (141 GB):
# GPTQ uses 138.91 GB (84 MB free), AWQ uses 138.49 GB (516 MB free),
# but repacking needs 768 MB. cpu-offload-gb doesn't help because the OOM
# occurs during process_weights_after_loading() before offloading runs.
# B200 (192 GB) solves this with ~53 GB of headroom.

app = modal.App(name="dynamic-unl-scoring")

sglang_image = (
    modal.Image.from_registry("lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime")
    .entrypoint([])
    .pip_install("huggingface_hub[hf_transfer]")
)

model_volume = modal.Volume.from_name("scoring-model-weights", create_if_missing=True)
HF_CACHE_PATH = "/root/.cache/huggingface"

sglang_image = sglang_image.env(
    {"HF_HUB_CACHE": HF_CACHE_PATH, "HF_XET_HIGH_PERFORMANCE": "1"}
)


def download_model(repo_id: str):
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=repo_id)


sglang_image = sglang_image.run_function(
    download_model,
    volumes={HF_CACHE_PATH: model_volume},
    args=(MODEL_ID,),
)

with sglang_image.imports():
    import requests


def wait_for_server(timeout: int = 10 * MINUTES):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(
                f"http://127.0.0.1:{SGLANG_PORT}/health", timeout=5
            )
            if resp.status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(5)
    raise TimeoutError(f"SGLang server not ready within {timeout}s")


@app.cls(
    image=sglang_image,
    gpu="B200",
    volumes={HF_CACHE_PATH: model_volume},
    timeout=20 * MINUTES,
    scaledown_window=5 * MINUTES,
)
class ScoringEndpoint:
    @modal.enter()
    def start_server(self):
        cmd = [
            "python",
            "-m",
            "sglang.launch_server",
            "--model-path",
            MODEL_ID,
            "--served-model-name",
            MODEL_ID,
            "--host",
            "0.0.0.0",
            "--port",
            str(SGLANG_PORT),
            "--tp",
            "1",
            "--attention-backend",
            "fa3",
            "--quantization",
            "awq_marlin",
            "--enable-deterministic-inference",
            "--enable-metrics",
        ]
        self.process = subprocess.Popen(cmd)
        wait_for_server()

    @modal.web_server(port=SGLANG_PORT, startup_timeout=15 * MINUTES)
    def serve(self):
        pass

    @modal.exit()
    def stop(self):
        self.process.terminate()


@app.local_entrypoint()
def test():
    import json
    import urllib.request

    url = ScoringEndpoint().serve.get_web_url()
    print(f"Endpoint URL: {url}")

    payload = json.dumps(
        {
            "model": MODEL_ID,
            "messages": [
                {
                    "role": "user",
                    "content": "Hello, who are you?",
                }
            ],
            "temperature": 0,
            "max_tokens": 64,
        }
    ).encode()

    deadline = time.time() + 15 * MINUTES
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
