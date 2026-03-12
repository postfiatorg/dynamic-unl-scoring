"""Deploy Qwen3-235B-A22B on Modal with SGLang for Dynamic UNL scoring.

Serves the model on a single H200 GPU with deterministic inference enabled.
Uses GPTQ-Int4 quantization (official Qwen). If GPTQ encounters OOM during
Marlin kernel repacking, switch MODEL_ID to the AWQ fallback below.

Usage:
    modal run infra/modal/scoring_endpoint.py      # Ephemeral test run
    modal deploy infra/modal/scoring_endpoint.py   # Persistent deployment
"""

import subprocess
import time

import modal

MINUTES = 60
SGLANG_PORT = 8000

MODEL_ID = "Qwen/Qwen3-235B-A22B-GPTQ-Int4"
FALLBACK_MODEL_ID = "QuixiAI/Qwen3-235B-A22B-AWQ"

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
    gpu="H200",
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
    from openai import OpenAI

    url = ScoringEndpoint().serve.get_web_url()
    print(f"Endpoint URL: {url}")

    client = OpenAI(base_url=f"{url}/v1", api_key="not-needed")

    deadline = time.time() + 15 * MINUTES
    while time.time() < deadline:
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {
                        "role": "user",
                        "content": "What is 2+2? Reply with just the number.",
                    }
                ],
                temperature=0,
                max_tokens=64,
                timeout=120,
            )
            elapsed = time.time() - start

            content = response.choices[0].message.content
            usage = response.usage
            print(f"\nResponse: {content}")
            print(f"Time: {elapsed:.1f}s")
            if usage:
                print(
                    f"Tokens: {usage.prompt_tokens} in"
                    f" / {usage.completion_tokens} out"
                )
            return
        except Exception as exc:
            print(f"Waiting for server... ({type(exc).__name__})")
            time.sleep(10)

    raise TimeoutError("No response from endpoint within timeout")
