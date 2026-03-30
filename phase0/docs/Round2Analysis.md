# Round 2 Model Benchmark Analysis

**Recommended model:** `qwen3-next-80b-instruct`

This is a different recommendation than Round 1, where thinking mode ranked first. The reasoning is straightforward: at 80B scale, the instruct variant achieves a level of cross-run determinism that no Round 1 model came close to, while maintaining acceptable penalty calibration and the best reasoning specificity of any Round 2 candidate. For a system that requires cross-validator reproducibility, that determinism advantage is decisive.

---

## Why This Analysis Differs from Round 1

Round 1's analysis (Round1Analysis.md) ranked `qwen3-235b-thinking` first on strategic grounds: future-task headroom, harsher penalty calibration, and the assumption that thinking mode's reasoning chain would matter more as scoring inputs got richer. That was the right call for 235B-scale models where all three candidates were operationally similar.

At 80B scale, the operational gap between thinking and instruct is no longer close. The instruct variant produces near-identical output every run. The thinking variant does not. When the design requires validators running the same model on the same data to converge on the same UNL, that gap matters more than any other dimension.

---

## Benchmark Summary

Session: `phase0/results/2026-03-12_21-26-03/` — 4 models, 5 runs each, temperature 0, same prompt and snapshot as Round 1.

### Completion Rate

| Model | Complete | Failed | Failure Cause |
|---|---|---|---|
| qwen3-32b | 5/5 | 0 | — |
| qwen3-next-80b-instruct | 4/5 | 1 | Truncated prompt from API (9,567 vs 15,291 tokens) |
| qwen3-next-80b-thinking | 4/5 | 1 | Hit max_tokens (16,384) before finishing JSON |
| gpt-oss-120b | 4/5 | 1 | Hit max_tokens (16,384) before finishing JSON |

The instruct failure was an upstream API error (OpenRouter delivered a truncated prompt), not a model limitation. The thinking and gpt-oss failures were genuine: the model ran out of output budget before completing the JSON response.

### Score Distribution Per Run

| Model | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Mean Range |
|---|---|---|---|---|---|---|
| qwen3-next-80b-thinking | 73.1 | 73.9 | 68.4 | 72.9 | ✗ | 68.4–73.9 |
| qwen3-next-80b-instruct | 83.3 | ✗ | 83.3 | 83.2 | 83.2 | 83.2–83.3 |
| qwen3-32b | 85.9 | 82.7 | 75.2 | 82.6 | 85.5 | 75.2–85.9 |
| gpt-oss-120b | 77.3 | 78.0 | 80.1 | ✗ | 83.0 | 77.3–83.0 |

The instruct variant's mean score varies by 0.1 points across runs. Every other model varies by 5–11 points.

---

## The Determinism Case

This is the single most important finding from Round 2 and the primary basis for the recommendation.

### Cross-Run Score Consistency

For each validator, compute the spread (max − min) of scores across all complete runs of a model.

| Model | Validators ≤3 spread | Validators ≤5 | Validators ≤10 | Validators >10 | Mean Spread | Max Spread |
|---|---|---|---|---|---|---|
| **qwen3-next-80b-instruct** | **41/42** | **42/42** | **42/42** | **0/42** | **0.3** | **5** |
| gpt-oss-120b | 4/42 | 12/42 | 35/42 | 7/42 | 8.3 | 31 |
| qwen3-32b | 0/42 | 2/42 | 21/42 | 21/42 | 11.1 | 23 |
| qwen3-next-80b-thinking | 0/42 | 10/42 | 26/42 | 16/42 | 11.7 | 35 |

41 of 42 validators score within ±3 points across the instruct model's runs. The worst-case spread is 5 points. No other model in either Round 1 or Round 2 comes close to this.

For comparison, Round 1's most stable model (`qwen3-235b-instruct`) had per-validator spreads reaching 26 points on edge cases. Round 2 instruct's worst case is 5.

### UNL Boundary Stability

| Model | Always Top 35 | Ever Top 35 | Borderline Pool | Avg Cutoff Gap | Pairwise UNL Overlap |
|---|---|---|---|---|---|
| **qwen3-next-80b-instruct** | **35** | **35** | **0** | **2.0** | **35.0/35** |
| gpt-oss-120b | 34 | 36 | 2 | 1.0 | 34.5/35 |
| qwen3-next-80b-thinking | 34 | 36 | 2 | 3.8 | 34.3/35 |
| qwen3-32b | 33 | 37 | 4 | 2.0 | 34.0/35 |

The instruct model produces the exact same top-35 UNL in every run. Zero borderline validators. Perfect pairwise overlap. This is what deterministic scoring looks like even on OpenRouter without SGLang's deterministic inference mode.

For Round 1, the best boundary behavior was `minimax-m2.5` with a borderline pool of 2. Round 2 instruct achieves 0.

---

## Penalty Calibration

The scoring prompt defines <99% 30-day agreement as a serious issue. Ten validators in the testnet snapshot fall below that threshold, seven below 97%.

| Model | Avg Score (≥0.99 cohort) | Avg Score (<0.99 cohort) | Avg Score (<0.97 cohort) | Penalty Delta |
|---|---|---|---|---|
| qwen3-next-80b-thinking | 83.4 | 36.0 | 28.7 | 47.4 |
| gpt-oss-120b | 87.3 | 55.0 | 46.2 | 32.3 |
| qwen3-next-80b-instruct | 90.0 | 61.7 | 50.9 | 28.3 |
| qwen3-32b | 88.8 | 61.9 | 52.4 | 26.9 |

The thinking variant penalizes hardest (47-point gap). The instruct variant is more lenient (28-point gap). This was the main argument for thinking mode in Round 1.

### Why the Penalty Gap Is Acceptable

Round 1's winner (`qwen3-235b-thinking`) had a penalty delta of ~29 points (avg 82.9 for strong vs avg 56.2 for <0.99). Round 2's instruct model at 28.3 points is in the same range. The thinking model at 47.4 points is actually an outlier — harsher than any Round 1 model.

More importantly: penalty calibration is tunable through prompt engineering. The prompt can explicitly specify score bands for agreement thresholds. Determinism is not tunable — a model either produces stable output or it doesn't.

A model that consistently scores a weak validator at 62 across every run is more useful for production UNL selection than one that scores it anywhere between 28 and 63 depending on the run.

---

## Reasoning Quality

Assessed on three validators: v002 (strong, 30d agreement = 1.0), v001 (weak, 30d = 0.956), v006 (failed, 30d = 0.008).

**qwen3-next-80b-instruct** produces the most specific reasoning of any model tested. For v001 (weak), it cites "30-day agreement drops to 95.56% with nearly 16k missed ledgers" — exact percentage and actual missed ledger count from the data. For v006 (failed), it cites "0% agreement in 1h/24h and only 0.8% in 30d." No other model references missed ledger counts.

**qwen3-32b** is also detailed: cites exact domain names, software versions, UNL status. Solid but less specific than instruct on the penalty-relevant validators.

**qwen3-next-80b-thinking** has detailed analysis in its thinking trace but terse inline reasoning. The production system uses the inline reasoning string, not the trace.

**gpt-oss-120b** is accurate but brief. References correct thresholds and agreement values but doesn't go deeper.

No hallucination detected in any model.

---

## Latency and Token Efficiency

| Model | Mean Latency (complete runs) | Latency Range | Mean Completion Tokens |
|---|---|---|---|
| **qwen3-next-80b-instruct** | **19.8s** | **9.8–28.6s** | **~3,000** |
| gpt-oss-120b | 34.6s | 23.9–54.3s | ~3,800 |
| qwen3-next-80b-thinking | 104.6s | 92.2–115.1s | ~17,000 |
| qwen3-32b | 317.9s | 74.3–806.7s | ~3,000 (except run 3: 23K) |

The instruct model is the fastest and most efficient. The thinking model uses 5–8x more tokens due to chain-of-thought. qwen3-32b has an unexplained latency spike on run 3 (807s, 23K tokens — likely internal reasoning leaking into output).

For production: a 20-second scoring round vs 100+ seconds matters for operational cadence, and lower token counts reduce self-hosted inference cost on Modal.

---

## Comparison to Round 1 Baselines

| Dimension | Round 1 Thinking (235B) | Round 1 Instruct (235B) | **Round 2 Instruct (80B)** |
|---|---|---|---|
| Completion rate | 8/8 | 8/8 | 4/5 (1 API error) |
| Mean score spread per validator | ~15–40 on edge cases | ~5–26 on edge cases | **0.3 mean, 5 max** |
| Borderline pool | 4 | 6 | **0** |
| Pairwise UNL overlap | 34.18/35 | 34.11/35 | **35.0/35** |
| Penalty delta (≥0.99 vs <0.99) | 26.7 | 20.4 | 28.3 |
| Mean latency | 111.6s | 32.7s | **19.8s** |
| LiveBench Reasoning | 59.40 | 58.43 | 54.75 |

The 80B instruct model is more deterministic than any 235B model, penalizes comparably to Round 1 thinking, is faster than Round 1 instruct, and — critically — actually fits on a single H200 with 100GB of headroom.

The LiveBench reasoning score dropped from 59.4 to 54.75 (−4.65 points). This does not appear to have degraded scoring quality on the validator task. The scores are well-differentiated, the reasoning cites real data, and the penalty calibration is in the same range as Round 1's top model.

---

## Strategic Ranking

| Rank | Model | Role | Why |
|---|---|---|---|
| 1 | **qwen3-next-80b-instruct** | Deploy | Overwhelming determinism advantage. Comparable penalties to Round 1 thinking. Best reasoning specificity. Fastest. Fits trivially on H200 (~40GB). |
| 2 | qwen3-next-80b-thinking | Challenger | Harshest penalty calibration. Worth revisiting if instruct proves too lenient in production. But 5x slower, 5x more tokens, and far less deterministic. |
| 3 | qwen3-32b | Fallback | 100% completion rate and detailed reasoning, but high variance and extreme latency outliers. Dense architecture means even smaller VRAM (~16GB). |
| 4 | gpt-oss-120b | Eliminated | No standout advantage on any dimension. Middle of the pack across the board. |

---

## What Comes Next

1. **Deploy `qwen3-next-80b-instruct` on Modal** — single H200, SGLang, deterministic inference. The infrastructure script is ready; only the model name changes.
2. **Confirm Marlin repacking succeeds** — at ~40GB weights, there is ~100GB headroom. This should not OOM.
3. **Run deterministic inference test** — same prompt, multiple runs on the same GPU instance. Verify bit-identical or near-identical output under SGLang's deterministic mode.
4. **If penalty calibration proves too lenient** — adjust the scoring prompt to specify explicit score bands for agreement thresholds, or evaluate the thinking variant as a replacement.
