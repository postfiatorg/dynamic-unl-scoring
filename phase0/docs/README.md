# Phase 0: Model Selection and Infrastructure

Phase 0 answers two questions: which model scores validators, and where does it run? Both are answered. The selected model is deployed on Modal with perfect deterministic inference confirmed across 5 full scoring runs.

---

### Summary

| | |
|---|---|
| **Model** | Qwen3-Next-80B-A3B-Instruct-FP8 (80B total, 3B active, MoE) |
| **Platform** | Modal serverless, single H200 GPU (141 GB VRAM) |
| **Inference engine** | SGLang v0.5.6 with `--enable-deterministic-inference` |
| **Determinism** | 100% — 5 runs, bit-identical output, 0 score variance |

| Scoring Results | |
|---|---|
| Validators scored | 42/42 |
| Score range | 5-97 (mean 85.31) |
| Prompt tokens | 15,291 |
| Completion tokens | 3,146 |
| Inference time (warm) | ~43s per run |
| Cold start (first request) | ~2 min (pre-compiled DeepGEMM) |
| Cost per scoring run | ~$0.38 (H200 at $4.54/hr) |

---

### Execution Manifest

Everything required to reproduce the scoring output.

| Component | Value |
|---|---|
| Model ID | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` |
| Quantization | FP8 (native, no Marlin repacking) |
| GPU | NVIDIA H200 (141 GB), single GPU (TP=1) |
| Inference engine | SGLang v0.5.6.post2 |
| Container image | `lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime` |
| CUDA version | 12.9 |
| Attention backend | FlashInfer (auto-selected) |
| Sampling backend | PyTorch (forced by deterministic mode) |
| Temperature | 0 (greedy decoding) |
| Scoring prompt | `prompts/scoring_v1.txt` |
| Validator snapshot | `data/testnet_snapshot.json` (42 validators, fetched 2026-03-10) |
| Deployment script | `infra/deploy_endpoint.py` |
| Key SGLang flags | `--mem-fraction-static 0.75`, `--chunked-prefill-size 4096`, `--max-running-requests 4` |

---

### Model Selection

Read in order. Each document builds on the previous decision.

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 1 | [ModelBenchmarkRound1.md](ModelBenchmarkRound1.md) | Which open-weight LLM fits on a single H200 and scores validators well? | Three finalists: qwen3-235b-thinking, minimax-m2.5, qwen3-235b-instruct |
| 2 | [Round1Analysis.md](Round1Analysis.md) | Which finalist is the best strategic fit for Dynamic UNL? | qwen3-235b-thinking ranked #1 for scoring philosophy and future headroom |
| 3 | [WhyNotThinking2507.md](WhyNotThinking2507.md) | Should we use the dedicated Thinking-2507 fine-tune instead? | No — 10x slower, 3x less stable, worse score calibration |
| 3b | [ModelBenchmarkRound2.md](ModelBenchmarkRound2.md) | All Round 1 models OOM on Modal — which smaller models fit? | Four candidates: qwen3-next-80b (thinking + instruct), qwen3-32b, gpt-oss-120b |
| 3c | [Round2Analysis.md](Round2Analysis.md) | Which Round 2 model should we deploy? | qwen3-next-80b-instruct — near-perfect determinism, comparable scoring quality to Round 1 |

### Infrastructure

Read in order. Each document picks up where the previous one hit a wall.

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 4 | [RunPodDeployment.md](RunPodDeployment.md) | How to deploy Qwen3-235B-A22B on RunPod serverless? | Setup guide written, but deployment failed (see next) |
| 5 | [WhyNotRunPodServerless.md](WhyNotRunPodServerless.md) | Why did RunPod fail after 9 attempts? | SGLang is broken on RunPod serverless — platform bug, community confirmed |
| 6 | [ModalEvaluation.md](ModalEvaluation.md) | Is Modal a viable alternative? | Yes — first-class SGLang support, H200/B200 available, recommended go |
| 7 | [ModalDeploymentAttempts.md](ModalDeploymentAttempts.md) | Did Modal work for 235B? | No — Qwen3-235B-A22B OOMs during Marlin repacking on every single GPU |
| 8 | [DeployQwen80B.md](DeployQwen80B.md) | Can the selected 80B model be deployed? | Yes — after fixing FlashInfer workspace buffer and memory tuning. Perfect determinism confirmed. |

### Data Sources

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 9 | [ASNSetup.md](ASNSetup.md) | How to identify validator ISP/cloud provider? | pyasn with local BGP routing table — fast, offline, public data, freely publishable |

### Phase 0 Decision Gate

| Criterion | Status |
|---|---|
| Open-weight model selected with acceptable scoring quality | Done — two benchmark rounds, model selected |
| GPU endpoint active and tested | Done — Modal with H200, 5 successful scoring runs |
| Full execution manifest defined | Done — see table above |
| Determinism confirmed | Done — 100% identical output across 5 runs (exceeds >99% target) |
| ASN data source selected and verified | Done — pyasn, 44 nodes across 13 ASNs |
| MaxMind GeoIP2 Insights access confirmed | Done — account ID 1314510, Precision Insights subscription active |

Phase 0 is complete. The next step is Phase 1: building the foundation scoring pipeline.
