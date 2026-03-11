# Model Comparison: qwen3-235b-thinking vs qwen3-235b-thinking-2507

Benchmark comparison for Milestone 0.2 deployment decision. The question: should we deploy the dedicated Thinking-2507 fine-tune instead of the base model we already benchmarked?

The answer is no. The base model is the better choice for Dynamic UNL on every dimension that matters.

---

## The Two Models

| | `qwen3-235b-thinking` | `qwen3-235b-thinking-2507` |
|---|---|---|
| HuggingFace ID | `Qwen/Qwen3-235B-A22B` | `Qwen/Qwen3-235B-A22B-Thinking-2507` |
| OpenRouter ID | `qwen/qwen3-235b-a22b` | `qwen/qwen3-235b-a22b-thinking-2507` |
| What it is | Base MoE model with thinking mode toggled via `reasoning.effort = "high"` | Separate fine-tune released July 2025, optimized specifically for extended thinking |
| Architecture | 235B total, 22B active (MoE) | Same architecture, different weights |
| Benchmark runs | 8 complete runs (March 10) | 2 complete, 1 rate-limited failure (March 11) |
| AWQ 4-bit size | ~118GB | ~118GB |

Both models have the same parameter count and the same VRAM footprint for weights. The critical differences are in behavior, not size.

---

## Head-to-Head Results

### Speed and Token Usage

| Metric | `qwen3-235b-thinking` | `qwen3-235b-thinking-2507` | Ratio |
|---|---|---|---|
| Avg time per run | 112s (~2 min) | 1,140s (~19 min) | **10.2x slower** |
| Avg completion tokens | 6,439 | 22,706 | 3.5x more |
| Avg reasoning text | 12,926 chars | 64,209 chars | 5.0x more |
| `max_tokens` required | 16,384 | 65,536 | 4x more headroom |
| Cost per run (OpenRouter) | $0.0035 | $0.0153 | 4.4x more expensive |

The Thinking-2507 model thinks extensively before answering. A simple "what is 2+2" question consumed 273 reasoning tokens before producing a one-word answer. On the 42-validator scoring prompt, it generates 60,000-68,000 characters of internal reasoning (compared to ~13,000 for the base model) and still produces the same structured JSON output at the end.

With the default `max_tokens=16384` from the benchmark script, the Thinking-2507 model exhausted all tokens on thinking and returned empty content on all 3 initial runs. It required `max_tokens=65536` to produce any output at all.

### Score Quality

| Metric | `qwen3-235b-thinking` (8 runs) | `qwen3-235b-thinking-2507` (2 runs) |
|---|---|---|
| Mean score (avg across runs) | 82.2 | 62.7 |
| Score range (typical run) | 0-96 | 8-91 |
| Score spread (typical run) | 85+ points | 62-82 points |
| Distribution shape | Smooth gradient with clear tiers | Bimodal (run 3) or compressed (run 1) |

The base model produces a natural score gradient: most healthy validators cluster at 84-90, with a clear degradation curve down through 70, 55, 43, 25, 5 for increasingly problematic validators. This is exactly what the scoring rubric asks for.

The Thinking-2507 model produces erratic distributions. Run 1 compressed almost everything into the 61-80 band (27 of 42 validators) with almost no differentiation at the top. Run 3 went bimodal: validators scored either 8-18 or 65-90 with nothing in between. Neither pattern is useful for UNL selection.

#### Score Distribution Buckets

| Bucket | Original (run 1) | 2507 (run 1) | 2507 (run 3) |
|---|---|---|---|
| 0-20 | 2 | 0 | 10 |
| 21-40 | 1 | 2 | 0 |
| 41-60 | 4 | 8 | 0 |
| 61-80 | 3 | 27 | 26 |
| 81-100 | 32 | 5 | 6 |

### Inter-Run Stability

| Metric | `qwen3-235b-thinking` | `qwen3-235b-thinking-2507` |
|---|---|---|
| Mean absolute score diff (pair) | 5.4 points | 16.4 points |
| Max score diff for same validator | 32 points | 68 points |
| Validators with >10pt diff | 5/42 (12%) | 18/42 (43%) |
| Internal UNL overlap (pair) | 34.2/35 avg | 33/35 |

The Thinking-2507 model's instability is severe. Validators v035 and v036 scored 85 in run 1 but 17 in run 3 — a 68-point swing at temperature 0. In run 1, the model's reasoning for v036 explicitly noted "very low 30-day agreement (84.76%)... indicating serious long-term issues" and then assigned a score of 85. The reasoning contradicted the score.

For a system where Phase 2 requires validator-side replay with convergence monitoring, this level of instability is disqualifying. The base model's 5.4-point average diff (already flagged as "the least stable numerically" in the Strategic Assessment) is manageable. A 16.4-point average diff is not.

### UNL Selection Agreement

Despite the score instability, the actual top-35 validator selection is surprisingly close between models:

- Cross-model consensus overlap: **32 of 34** consensus validators agree
- Only 2 validators differ: v011 and v033 are in the original's consensus but not the 2507's; v035 is in the 2507's but not the original's

This confirms the earlier Strategic Assessment finding: the model choice matters less for *which* 35 validators are selected today and more for boundary behavior, stability, and future-proofing.

### Reasoning Quality

The Thinking-2507 model produces 5x more reasoning text but lower-quality conclusions:

**Base model (v036, 30d agreement 84.76%, scored 25):**
> "Low 30-day agreement (84.76%). Domain unverified. Below the reliability threshold expected for UNL inclusion."

Concise. The score matches the reasoning. The penalty is appropriate.

**Thinking-2507 run 1 (v036, 30d agreement 84.76%, scored 85):**
> "Perfect 1h and 24h agreement, with very low 30-day agreement (84.76%), indicating serious long-term issues. Domain verified. Current software version with aligned fee votes."

The reasoning says "serious long-term issues" but the score is 85. The model overthought itself into a contradictory conclusion.

**Thinking-2507 run 3 (v036, 30d agreement 84.76%, scored 17):**
> "Very low 30-day agreement (84.76%). No domain."

Terse but the score now matches. Except the same model gave 85 one run earlier.

---

## The H200 VRAM Problem

Both models weigh ~118GB at AWQ 4-bit, leaving ~23GB on an H200 (141GB) for KV cache and engine overhead. But they have very different KV cache requirements because of sequence length:

| | `qwen3-235b-thinking` | `qwen3-235b-thinking-2507` |
|---|---|---|
| Prompt tokens | ~15,300 | ~15,300 |
| Completion tokens (avg) | 6,439 | 22,706 |
| Total sequence length | ~21,700 | ~38,000 |
| `max_model_len` needed | 32,768 (comfortable) | 65,536 (tight) |

KV cache size scales linearly with sequence length. The Thinking-2507 model's sequences are 1.75x longer on average, which means 1.75x more KV cache memory.

With only 23GB of headroom after loading weights, the base model at `max_model_len=32768` is comfortable. The Thinking-2507 model at `max_model_len=65536` is a real risk for OOM on a single H200 — the KV cache for a 38K-token sequence on a 235B MoE model may consume most of that 23GB budget, leaving little room for engine overhead, activations, and the batch scheduler.

If the KV cache exceeds available VRAM, the endpoint will either:
- Fail with OOM during inference (after a 5-10 minute cold start, wasting money)
- Require reducing `max_model_len`, which risks truncating the thinking trace and producing empty or incomplete output (exactly what happened with `max_tokens=16384` on OpenRouter)

The base model does not have this problem. Its sequences fit comfortably within 32K with room to spare.

---

## The Quantization Concern

The user raised a fair question: will the 4-bit AWQ version of Thinking-2507 be worse than the base model at full precision?

The answer is that it's the wrong comparison. Even at full precision on OpenRouter, the Thinking-2507 model already performed worse than the base model on this specific task. Quantization would only degrade it further. The quality gap is not caused by precision — it's caused by the model's fine-tuning making it overthink simple structured-output tasks, leading to score compression, bimodal distributions, and reasoning-score contradictions.

Quantization typically costs 1-3% on general benchmarks. That's noise compared to the 16.4-point inter-run instability and the fundamental calibration problems this model exhibits on the validator scoring task.

---

## Why More Thinking Is Not Better Here

The Thinking-2507 model was fine-tuned for tasks that benefit from extended reasoning: mathematical proofs, complex coding problems, scientific analysis. These are tasks where thinking longer genuinely helps.

Validator scoring is not that kind of task. The scoring rubric is explicit and mechanical:
- Agreement > 99.9%? High score.
- Agreement < 99%? Serious issue.
- Domain verified? Bonus.
- Underrepresented geography? Bonus.

The base model processes these rules in ~13K characters of reasoning and arrives at well-calibrated scores. The Thinking-2507 model processes the same rules in ~64K characters, second-guessing itself, weighing contradictory factors, and arriving at worse scores. The extended thinking is counterproductive for this task.

---

## Recommendation

**Deploy `Qwen/Qwen3-235B-A22B` (the base model) on RunPod. Do not deploy the Thinking-2507 variant.**

| Factor | Base Model | Thinking-2507 | Winner |
|---|---|---|---|
| Scoring quality | Smooth gradient, well-calibrated | Compressed or bimodal, miscalibrated | Base |
| Inter-run stability | 5.4pt avg diff | 16.4pt avg diff | Base |
| Speed | ~112s per run | ~1,140s per run | Base |
| Token cost | 6,439 completion tokens | 22,706 completion tokens | Base |
| H200 VRAM headroom | Comfortable (32K seq len) | Risky (65K seq len, tight KV cache) | Base |
| `max_tokens` requirement | 16,384 | 65,536 (fails below this) | Base |
| Benchmark evidence | 8 complete runs, well-analyzed | 2 complete runs, 1 failure | Base |
| Reasoning-score consistency | Scores match reasoning | Run 1 contradicts its own reasoning | Base |

The base model wins on every dimension. The Thinking-2507 variant was designed for a different class of problems and is a poor fit for structured validator scoring.

For RunPod deployment:
- Model: `Qwen/Qwen3-235B-A22B` (or a pre-quantized AWQ variant if available)
- Enable thinking mode via prompt-level `/think` tokens (same as OpenRouter's `reasoning.effort = "high"`)
- `max_model_len=32768` — comfortable fit on H200
- `max_tokens=16384` — sufficient for this model's output

---

## What This Means for the Deployment Guide

The `for-claude-llm-only-sensitive/deploy-qwen3-235b-runpod.md` guide should be updated to use the base model `Qwen/Qwen3-235B-A22B` instead of `Qwen/Qwen3-235B-A22B-Thinking-2507`. The base model is what was validated across 8 benchmark runs and is the model recommended in the Strategic Assessment — the Thinking-2507 detour confirmed that the original choice was correct.
