# Modal/SGLang Evaluation: Qwen3.6 27B FP8

Date: 2026-04-30

Candidate: `Qwen/Qwen3.6-27B-FP8`

Baseline deployment reference: `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`

Related quality analysis: [ModelQualityComparison_Qwen36_27B.md](ModelQualityComparison_Qwen36_27B.md)

## Deployment Profile

Qwen3.6 uses a dedicated Modal/SGLang profile documented in [DeployQwen36_27B.md](DeployQwen36_27B.md).

The selected configuration is H100, the official FP8 checkpoint, SGLang `nightly-dev-cu13-20260430-e60c60ef` pinned by digest, deterministic inference, DeepGEMM precompile, and the same `0.75` memory fraction used by the Qwen3-Next baseline. SGLang auto-detects the FP8 checkpoint; the wrapper does not pass an explicit quantization flag for Qwen3.6.

The Qwen3.6 FP8 profile uses the pinned main-branch SGLang image because the stable `v0.5.10.post1-runtime` image produced corrupted smoke-test output matching upstream issue [#23687](https://github.com/sgl-project/sglang/issues/23687). The issue reporter confirmed the same model works on `dev-cu13`; the wrapper uses the dated nightly tag plus digest for reproducibility.

The Qwen3.6 wrapper skips the separate build-time Hugging Face preload step and uses the mounted Modal volume cache populated by the initial deployment. DeepGEMM compilation and serving still mount the same model-specific volume.

## Repository Changes

The Modal deployment path now separates shared implementation from model-specific wrappers:

- `infra/deploy_endpoint.py` is the generic reusable Modal/SGLang implementation.
- `infra/deploy_qwen3_next_endpoint.py` is the Qwen3-Next baseline wrapper.
- `infra/deploy_qwen36_endpoint.py` is the Qwen3.6 deployment wrapper.

The self-hosted scoring script now supports both prompt contracts:

- `--prompt-version v1` for comparison with the historical Modal baseline
- `--prompt-version v2` for the active Dynamic UNL scoring contract
- `--disable-thinking` for Qwen models that otherwise emit thinking text before the final answer

Modal outputs are written under:

```text
phase0/results/modal/
```

## Test Matrix

| Layer | Purpose | Required runs |
|---|---|---:|
| Smoke prompt | Confirms startup and OpenAI-compatible serving | 1 |
| `scoring_v2` | Tests the active Dynamic UNL contract, dimension fields, and `network_summary` | 5 |
| `historical_v1` | Allows direct comparison with the existing Qwen3-Next Modal baseline | 5 |

The existing baseline captures are:

```text
phase0/results/modal/qwen3-next-80b-instruct/2026-03-13_12-35-32/
```

They demonstrate deterministic full-prompt behavior for Qwen3-Next on Modal/SGLang, but they use the historical v1 prompt. If a current-prompt Modal baseline is needed, run Qwen3-Next again with `--prompt-version v2`.

## Commands

Run the smoke test:

```bash
modal run infra/deploy_qwen36_endpoint.py
```

Deploy the persistent endpoint:

```bash
modal deploy infra/deploy_qwen36_endpoint.py
```

## Capture Commands

After persistent deploy, capture the current scoring contract:

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

Then capture the historical prompt for direct Modal-baseline comparison:

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

## Validation Criteria

The captured runs should show:

- 5/5 JSON-valid scoring runs
- 5/5 complete validator result sets
- zero invalid `scoring_v2` dimension fields
- `network_summary` present on all `scoring_v2` runs
- identical or acceptably stable score outputs across repeated `temperature=0` runs
- stable top-35 selection across repeated runs
- no reasoning spillover that corrupts JSON extraction
- Modal startup and cold-start behavior that is operationally tolerable for low-frequency scoring

## Captured Outputs

| Prompt layer | Results folder | Runs |
|---|---|---:|
| `scoring_v2` | `phase0/results/modal/qwen36-27b-fp8/2026-04-30_qwen36-27b-fp8_scoring-v2/` | 5 |
| `historical_v1` | `phase0/results/modal/qwen36-27b-fp8/2026-04-30_qwen36-27b-fp8_historical-v1/` | 5 |

## Modal Results

| Check | `scoring_v2` | `historical_v1` |
|---|---:|---:|
| JSON-valid runs | 5/5 | 5/5 |
| Complete result sets | 5/5 | 5/5 |
| Validators scored | 42/42 | 42/42 |
| Finish reason | `stop` on all runs | `stop` on all runs |
| Reasoning text leakage | none | none |
| Unique extracted-answer hashes | 1 | 1 |
| Unique score-map hashes | 1 | 1 |
| Unique top-35 hashes | 1 | 1 |
| Validators with score spread across runs | 0 | 0 |
| Maximum score spread | 0 | 0 |
| Top-35 intersection across 5 runs | 35/35 | 35/35 |
| Mean elapsed time | 87.99s | 47.83s |
| Prompt tokens | 7,654 | 15,324 |
| Completion tokens | 4,774 | 2,302 |
| Total tokens | 12,428 | 17,626 |

The active `scoring_v2` contract passed on every run: `network_summary` was present, all 42 validators had complete dimension fields, and `invalid_dimension_fields` was empty.

## Comparison

The existing Qwen3-Next Modal baseline remains perfectly deterministic on the historical prompt. Qwen3.6 now matches that determinism standard on both the historical prompt and the active `scoring_v2` prompt.

| Comparison | Result |
|---|---|
| Qwen3.6 Modal `historical_v1` vs Qwen3-Next Modal `historical_v1` | 42 common validators, top-35 overlap 34/35 |
| Qwen3.6 Modal `scoring_v2` vs Qwen3.6 OpenRouter `scoring_v2` | mean score difference -0.02, mean absolute difference 0.12, top-35 overlap 35/35 |
| Qwen3.6 Modal `scoring_v2` vs Qwen3-Next OpenRouter `scoring_v2` | mean score difference -6.79, mean absolute difference 6.79, top-35 overlap 34/35 |

The self-hosted Qwen3.6 run is materially more stable than the OpenRouter convenience runs. In the OpenRouter `scoring_v2` comparison, Qwen3.6 varied across 34 validators with maximum spread 9; the Modal/SGLang Qwen3.6 run varied across 0 validators with maximum spread 0.

The historical-prompt score scale is lower for Qwen3.6 than Qwen3-Next on Modal: mean 81.12 vs 85.31. This is a calibration difference, not a determinism failure. The top-35 decision changes by one validator (`v025` enters, `v033` exits).

## Deployment Notes

The working deployment depends on the pinned main-branch SGLang image because stable `v0.5.10.post1-runtime` produced corrupted Qwen3.6 FP8 output. This is a framework packaging caveat, not an observed model-quality issue after the pinned image change.

The Modal wrapper mounts the Hugging Face cache at `/model-cache/huggingface` because the `dev-cu13` image already has files under `/root/.cache/huggingface`, and Modal does not mount volumes over non-empty image paths. Qwen3.6 also disables the separate build-time preload step and uses the model-specific Modal volume cache during DeepGEMM compilation and serving.

## Recommendation State

Current recommendation: use Qwen3.6 as the active Dynamic UNL scoring model.

The quality comparison already favored Qwen3.6. The missing gate was self-hosted Modal/SGLang behavior: clean startup, valid JSON, no thinking leakage, repeated-run determinism, and stable top-35 output. The captured Modal results now pass that gate.

Qwen3-Next should remain as the historical fallback baseline for comparison and audit context. Qwen3.6 is the stronger model choice for the next Dynamic UNL scoring phase.
