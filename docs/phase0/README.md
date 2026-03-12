# Phase 0: Model Selection and Infrastructure

Phase 0 answers two questions: which model scores validators, and where does it run? The documents below follow the decision chain from model benchmarking through deployment attempts on two platforms.

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
| 7 | [ModalDeploymentAttempts.md](ModalDeploymentAttempts.md) | Did Modal work? | No — Qwen3-235B-A22B OOMs during Marlin repacking on every single GPU |

### Where Things Stand

Model selection is complete. `qwen3-next-80b-instruct` (80B MoE, 3B active, ~40GB at 4-bit) is the selected model — it fits on a single H200 with ~100GB headroom, produces near-identical scores across runs, and maintains scoring quality comparable to the Round 1 235B candidates. The next step is deploying it on Modal with SGLang deterministic inference.
