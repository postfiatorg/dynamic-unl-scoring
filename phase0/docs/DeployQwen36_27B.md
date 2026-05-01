# Self-Hosted Deployment: Qwen3.6 27B FP8 on Modal

Date: 2026-04-30

Following the quality comparison in [ModelQualityComparison_Qwen36_27B.md](ModelQualityComparison_Qwen36_27B.md), Qwen3.6 uses a dedicated Modal/SGLang deployment profile. This document is the deployment source of truth for that profile.

## Deployment Profile

| Component | Value |
|---|---|
| Model ID | `Qwen/Qwen3.6-27B-FP8` |
| Short model name | `qwen36-27b-fp8` |
| Modal app name | `dynamic-unl-scoring-qwen36` |
| Modal volume | `scoring-model-weights-qwen36` |
| Deployment wrapper | `infra/deploy_qwen36_endpoint.py` |
| Shared implementation | `infra/deploy_endpoint.py` |
| GPU | `H100` |
| Tensor parallelism | `1` |
| Checkpoint format | FP8 checkpoint, auto-detected by SGLang |
| Explicit SGLang quantization flag | none |
| SGLang image | `lmsysorg/sglang:nightly-dev-cu13-20260430-e60c60ef@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65` |
| Reasoning parser | `qwen3` |
| Determinism | `--enable-deterministic-inference` |
| Trust remote code | enabled |
| FlashInfer workspace | `2147483648` bytes |
| Static memory fraction | `0.75` |
| Chunked prefill size | `4096` |
| Max running requests | `1` |
| Build-time model preload | disabled; use mounted Modal volume cache |
| DeepGEMM precompile | enabled, on H100 |
| Scaledown window | `20` minutes |
| Web server startup timeout | `35` minutes |

## Rationale

H100 is the selected GPU because the checkpoint is FP8 and H100 has native FP8 Tensor Core support. L40S is not used because the full-context scoring run should not start from a tighter-memory GPU. A100-80GB is not used because it does not provide native FP8 Tensor Core support.

The Qwen3.6 wrapper serves the FP8 checkpoint directly and does not pass an explicit `--quantization fp8` flag. Qwen's SGLang example for `Qwen/Qwen3.6-27B-FP8` uses the FP8 model path directly, letting the runtime detect the checkpoint format.

The SGLang image is pinned to the dated nightly tag and digest currently backing `lmsysorg/sglang:dev-cu13`. The stable `v0.5.10.post1-runtime` image is not used for this profile because smoke prompts produced deterministic corrupted output matching upstream SGLang issue [#23687](https://github.com/sgl-project/sglang/issues/23687). The issue reporter confirmed the Qwen3.6 FP8 path works on the main-branch `dev-cu13` image, and the dated nightly tag avoids depending on the moving `dev-cu13` tag.

The memory profile intentionally matches the Qwen3-Next baseline where possible:

```text
--mem-fraction-static 0.75
--chunked-prefill-size 4096
```

This leaves runtime headroom for the full scoring prompt and the FlashInfer workspace instead of maximizing KV-cache reservation.

DeepGEMM precompile is enabled because this checkpoint uses FP8. Precompiling during image build makes the build slower, but keeps that compile work out of cold starts.

The wrapper skips the separate build-time `snapshot_download()` preload step. The Qwen3.6 weights are already cached in the model-specific Modal volume from the initial deployment, and the volume is mounted during both DeepGEMM compilation and serving.

No context-length cap is configured. The deployment uses the model/runtime context behavior rather than shrinking context for memory.

## Commands

Run the smoke test:

```bash
modal run infra/deploy_qwen36_endpoint.py
```

Deploy the persistent endpoint:

```bash
modal deploy infra/deploy_qwen36_endpoint.py
```

Endpoint URL format:

```text
https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run
```

Capture the active scoring contract:

```bash
python scripts/score_validators.py \
  --url https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run/v1 \
  --model-id Qwen/Qwen3.6-27B-FP8 \
  --model-name qwen36-27b-fp8 \
  --prompt-version v2 \
  --disable-thinking \
  --runs 5 \
  --session-name 2026-04-30_qwen36-27b-fp8_scoring-v2
```

Capture the historical prompt for direct comparison against the existing Qwen3-Next Modal baseline:

```bash
python scripts/score_validators.py \
  --url https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run/v1 \
  --model-id Qwen/Qwen3.6-27B-FP8 \
  --model-name qwen36-27b-fp8 \
  --prompt-version v1 \
  --disable-thinking \
  --runs 5 \
  --session-name 2026-04-30_qwen36-27b-fp8_historical-v1
```

Raw outputs are stored under:

```text
phase0/results/modal/qwen36-27b-fp8/
```

## Validation Outputs

The Modal/SGLang evaluation captured:

- smoke-test response, token usage, and latency
- 5 `scoring_v2` runs
- 5 `historical_v1` runs
- JSON/schema compliance
- repeated-output determinism at `temperature=0`
- top-35 consistency
- latency and token usage
- startup and cold-start observations

## Baseline Comparison

The existing Qwen3-Next Modal baseline is:

```text
phase0/results/modal/qwen3-next-80b-instruct/2026-03-13_12-35-32/
```

That baseline uses the historical v1 prompt. The `scoring_v2` Qwen3.6 captures should also be compared against the OpenRouter `scoring_v2` results from:

```text
phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/
```

## Status

The deployment profile is selected and validated with the main-branch SGLang image needed for Qwen3.6 FP8. Raw Modal/SGLang captures are stored under `phase0/results/modal/qwen36-27b-fp8/`; the feasibility recommendation is documented in [Qwen36ModalFeasibility.md](Qwen36ModalFeasibility.md).
