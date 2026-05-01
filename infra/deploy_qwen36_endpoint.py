"""Deploy the active Qwen3.6 27B FP8 scoring endpoint on Modal."""

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MODEL_SPEC = {
    "SCORING_APP_NAME": "dynamic-unl-scoring-qwen36",
    "SCORING_MODEL_VOLUME": "scoring-model-weights-qwen36",
    "SCORING_MODEL_ID": "Qwen/Qwen3.6-27B-FP8",
    "SCORING_GPU_TYPE": "H100",
    "SCORING_QUANTIZATION": "",
    "SCORING_SGLANG_IMAGE_TAG": (
        "lmsysorg/sglang:nightly-dev-cu13-20260430-e60c60ef"
        "@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65"
    ),
    "SCORING_REASONING_PARSER": "qwen3",
    "SCORING_MEM_FRACTION": "0.75",
    "SCORING_CHUNKED_PREFILL": "4096",
    "SCORING_MAX_REQS": "1",
    "SCORING_PRELOAD_MODEL": "0",
    "SCORING_COMPILE_DEEPGEMM": "1",
    "SCORING_COMPILE_GPU_TYPE": "H100",
}

for key, value in MODEL_SPEC.items():
    os.environ[key] = value

from deploy_endpoint import ScoringEndpoint, app, smoke_test  # noqa: E402,F401
