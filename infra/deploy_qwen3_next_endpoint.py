"""Deploy the Qwen3-Next baseline scoring endpoint on Modal."""

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MODEL_SPEC = {
    "SCORING_APP_NAME": "dynamic-unl-scoring",
    "SCORING_MODEL_VOLUME": "scoring-model-weights",
    "SCORING_MODEL_ID": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
    "SCORING_GPU_TYPE": "H200",
    "SCORING_QUANTIZATION": "fp8",
    "SCORING_SGLANG_IMAGE_TAG": "lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime",
    "SCORING_MEM_FRACTION": "0.75",
    "SCORING_CHUNKED_PREFILL": "4096",
    "SCORING_MAX_REQS": "4",
    "SCORING_COMPILE_DEEPGEMM": "1",
    "SCORING_COMPILE_GPU_TYPE": "H200",
}

for key, value in MODEL_SPEC.items():
    os.environ[key] = value

from deploy_endpoint import ScoringEndpoint, app, smoke_test  # noqa: E402,F401
