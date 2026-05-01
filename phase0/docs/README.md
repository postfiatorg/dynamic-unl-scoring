# Phase 0 Documentation Index

Phase 0 selected and deployed Qwen3-Next 80B A3B on Modal as the original baseline. The later Qwen3.6 work selected `Qwen/Qwen3.6-27B-FP8` as the active scoring model, with its own quality report, deployment profile, and Modal/SGLang validation.

## Deployment Profiles

| Model | Role | Deployment doc | Wrapper | Modal results |
|---|---|---|---|---|
| Qwen3.6 27B FP8 | Active scorer | [DeployQwen36_27B.md](DeployQwen36_27B.md) | `infra/deploy_qwen36_endpoint.py` | `phase0/results/modal/qwen36-27b-fp8/` |
| Qwen3-Next 80B A3B | Historical baseline | [DeployQwen80B.md](DeployQwen80B.md) | `infra/deploy_qwen3_next_endpoint.py` | `phase0/results/modal/qwen3-next-80b-instruct/2026-03-13_12-35-32/` |

## Historical Phase 0 Baseline

| Item | Value |
|---|---|
| Model | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` |
| Platform | Modal serverless |
| GPU | H200 |
| Inference engine | SGLang `v0.5.6.post2` |
| Prompt/result layer | Historical Phase 0 prompt, `prompts/scoring_v1.txt` |
| Determinism result | 5 full scoring runs, bit-identical output |

## Active Qwen3.6 Scorer

| Item | Value |
|---|---|
| Model | `Qwen/Qwen3.6-27B-FP8` |
| Platform | Modal serverless |
| GPU | H100 |
| Inference engine | SGLang `nightly-dev-cu13-20260430-e60c60ef`, pinned by digest |
| Prompt/result layers | `scoring_v2` and `historical_v1` |
| Status | Active production scoring model; non-thinking mode is the default request contract |

## Read Order

### Model Selection

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 1 | [ModelBenchmarkRound1.md](ModelBenchmarkRound1.md) | Which open-weight LLM fits on a single H200 and scores validators well? | Three finalists: qwen3-235b-thinking, minimax-m2.5, qwen3-235b-instruct. |
| 2 | [Round1Analysis.md](Round1Analysis.md) | Which finalist is the best strategic fit for Dynamic UNL? | qwen3-235b-thinking ranked first for scoring philosophy and future headroom. |
| 3 | [WhyNotThinking2507.md](WhyNotThinking2507.md) | Should the dedicated Thinking-2507 fine-tune be used? | No: slower, less stable, worse score calibration. |
| 4 | [ModelBenchmarkRound2.md](ModelBenchmarkRound2.md) | After 235B Modal OOMs, which smaller models fit? | Four candidates moved forward. |
| 5 | [Round2Analysis.md](Round2Analysis.md) | Which Round 2 model should be deployed? | Qwen3-Next 80B A3B Instruct. |

### Infrastructure

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 6 | [RunPodDeployment.md](RunPodDeployment.md) | How would Qwen3-235B deploy on RunPod serverless? | Setup documented, deployment failed. |
| 7 | [WhyNotRunPodServerless.md](WhyNotRunPodServerless.md) | Why did RunPod fail after repeated attempts? | Serverless SGLang path was not viable. |
| 8 | [ModalEvaluation.md](ModalEvaluation.md) | Is Modal a viable alternative? | Yes: SGLang support and H200/B200 availability. |
| 9 | [ModalDeploymentAttempts.md](ModalDeploymentAttempts.md) | Did Modal work for 235B? | No: Marlin repacking OOM on single-GPU paths. |
| 10 | [DeployQwen80B.md](DeployQwen80B.md) | Can Qwen3-Next 80B deploy deterministically? | Yes: deterministic full-prompt output confirmed. |

### Qwen3.6 Re-Evaluation

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 11 | [ModelQualityComparison_Qwen36_27B.md](ModelQualityComparison_Qwen36_27B.md) | Is Qwen3.6 a better quality candidate than Qwen3-Next? | Yes, quality-first winner on the saved comparison. |
| 12 | [DeployQwen36_27B.md](DeployQwen36_27B.md) | What is the selected Modal/SGLang deployment profile for Qwen3.6? | H100, FP8, pinned SGLang image, DeepGEMM precompile. |
| 13 | [Qwen36ModalFeasibility.md](Qwen36ModalFeasibility.md) | Which Modal/SGLang outputs validate Qwen3.6? | 5/5 valid deterministic runs on both prompt layers; continue with Qwen3.6. |
| 14 | [Qwen36ThinkingModeComparison.md](Qwen36ThinkingModeComparison.md) | Should Qwen3.6 run with thinking enabled? | No for production default; thinking is valid but slower and does not change top-35. |

### Data Sources

| # | Document | Question Answered | Outcome |
|---|---|---|---|
| 15 | [ASNSetup.md](ASNSetup.md) | How is validator ISP/cloud provider identified? | pyasn with local BGP routing table. |
