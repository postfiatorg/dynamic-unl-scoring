"""Deploy the Qwen3.8 27B FP8 candidate-evaluation endpoint on Modal.

Candidate under evaluation as a potential scoring-model successor; this
wrapper is not a production endpoint. The revision and runtime image are
pinned here so the evaluation record can cite one reviewable source.
"""

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


MODEL_SPEC = {
    "SCORING_APP_NAME": "dynamic-unl-scoring-qwen38",
    "SCORING_MODEL_VOLUME": "scoring-model-weights-qwen38",
    "SCORING_MODEL_ID": "Qwen/Qwen3.8-27B-FP8",
    "SCORING_MODEL_REVISION": "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",
    "SCORING_GPU_TYPE": "H100",
    "SCORING_QUANTIZATION": "",
    "SCORING_SGLANG_IMAGE_TAG": (
        "lmsysorg/sglang:nightly-dev-cu13-20260817-d91c3682"
        "@sha256:fa8774dd128600a09fd6d46670b06fb69a55dac8a3881e50ccf0916a45eb39af"
    ),
    "SCORING_REASONING_PARSER": "qwen3",
    "SCORING_MEM_FRACTION": "0.75",
    "SCORING_CHUNKED_PREFILL": "4096",
    "SCORING_MAX_REQS": "1",
    "SCORING_PRELOAD_MODEL": "0",
    # The Qwen3.6-era DeepGEMM precompile step fails against this model on
    # the 20260817 image (builder exit 1); it is a kernel warm-up only, so
    # the candidate profile skips it and accepts a slower first request.
    "SCORING_COMPILE_DEEPGEMM": "0",
    "SCORING_COMPILE_GPU_TYPE": "H100",
    # This model's prefix-cache-hit path is not covered by deterministic
    # inference on the pinned image (first execution of a request differs
    # from its repeats, each path individually bit-stable). Forcing the
    # fresh-prefill path restores repeat-identical outputs and matches the
    # production topology, where every round's request runs exactly once.
    "SCORING_DISABLE_RADIX_CACHE": "1",
}

for key, value in MODEL_SPEC.items():
    os.environ[key] = value

from infra.deploy_endpoint import ScoringEndpoint, app, smoke_test  # noqa: E402,F401
