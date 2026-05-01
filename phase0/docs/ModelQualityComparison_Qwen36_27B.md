# Quality Comparison: Qwen3.6 27B vs Qwen3-Next 80B A3B

Date: 2026-04-29

Selected model: `qwen/qwen3.6-27b`

Baseline at comparison time: `qwen/qwen3-next-80b-a3b-instruct`

## Decision

Quality-first winner: `qwen/qwen3.6-27b`.

This is not because it changed the current UNL set. On the current `scoring_v2` test, both models selected the same mean top-35 validators. The reason qwen3.6 is the better quality choice is that it combines:

- much stronger independent model-quality benchmarks
- full JSON/schema compliance on the Dynamic UNL prompts
- no loss in current top-35 UNL selection
- stricter treatment of weak and failed validators, if Dynamic UNL prefers harsher penalties for consensus failure
- lower worst-case cross-run score spread on the current prompt

The current baseline has one clear quality-side advantage and one non-quality operational advantage in this comparison:

- more verbose inline reasoning
- faster OpenRouter provider-path latency

Speed is not a quality criterion for this decision. Reasoning verbosity matters, but the explanation-quality evidence is mixed rather than a clean baseline win.

## What Was Compared

The comparison used the frozen Phase 0 snapshot:

- `data/testnet_snapshot.json`
- 42 validators
- 5 runs per model per prompt layer
- `temperature=0`
- JSON response mode
- OpenRouter API

Two prompt layers were tested:

| Layer | Purpose |
|---|---|
| `historical_v1` | Repeats the original Phase 0 benchmark style using `prompts/scoring_v1.txt`. |
| `scoring_v2` | Uses the current scoring contract from `prompts/scoring_v2.txt`, including dimension scores and `network_summary`. |

Raw results:

- `phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/`
- `analysis_summary.json`
- `openrouter_artificial_analysis_benchmarks.json`
- 20 raw model outputs: 2 models x 2 prompt layers x 5 runs

## Executive Readout

| Question | Factual answer |
|---|---|
| Which model is stronger on independent public model benchmarks? | qwen3.6, by a large margin. |
| Did qwen3.6 fail JSON or schema compliance? | No. It completed 5/5 runs on both prompt layers. |
| Did qwen3.6 change the current `scoring_v2` top-35 UNL? | No. Mean top-35 overlap was 35/35. |
| Did qwen3.6 score validators identically to the baseline? | No. It used a lower and harsher score scale. |
| Which model penalized weak validators more strongly on `scoring_v2`? | qwen3.6. This is a quality advantage only if the desired scoring policy is harsher consensus-failure penalties. |
| Which model had lower worst-case score instability on `scoring_v2`? | qwen3.6. |
| Which model gave longer inline explanations? | Qwen3-Next 80B A3B. Explanation quality overall is mixed. |
| Which model is the better quality candidate overall? | qwen3.6. |

## Public Model-Quality Benchmarks

OpenRouter Artificial Analysis data:

| Metric | Qwen3-Next 80B A3B | qwen3.6 27B | Winner |
|---|---:|---:|---|
| Intelligence Index | 20.1 | 45.8 | qwen3.6 |
| Coding Index | 15.3 | 36.5 | qwen3.6 |
| Agentic Index | 14.2 | 62.9 | qwen3.6 |
| Intelligence percentile | 42 | 90 | qwen3.6 |
| Coding percentile | 42 | 84 | qwen3.6 |
| Agentic percentile | 34 | 95 | qwen3.6 |
| GPQA | 73.8% | 84.2% | qwen3.6 |
| HLE | 7.3% | 21.6% | qwen3.6 |
| IFBench | 39.7% | 67.6% | qwen3.6 |
| `tau2` | 21.6% | 94.2% | qwen3.6 |
| AA-LCR | 51.3% | 68.7% | qwen3.6 |
| GDPval-AA | 6.3% | 45.8% | qwen3.6 |
| TerminalBench Hard | 7.6% | 34.8% | qwen3.6 |
| SciCode | 30.7% | 39.8% | qwen3.6 |
| CritPt | 0.0% | 1.1% | qwen3.6 |

Strict interpretation: qwen3.6 is the stronger general model by external benchmark evidence. This does not automatically prove it is better for Dynamic UNL, but it is strong prior evidence.

## Dynamic UNL Output Compliance

| Layer | Qwen3-Next 80B A3B | qwen3.6 27B | Winner |
|---|---:|---:|---|
| `historical_v1` complete runs | 5/5 | 5/5 | Tie |
| `historical_v1` JSON-valid runs | 5/5 | 5/5 | Tie |
| `scoring_v2` complete runs | 5/5 | 5/5 | Tie |
| `scoring_v2` JSON-valid runs | 5/5 | 5/5 | Tie |
| `scoring_v2` invalid dimension fields | 0 | 0 | Tie |
| `scoring_v2` runs with `network_summary` | 5/5 | 5/5 | Tie |

Strict interpretation: qwen3.6 has no schema-compliance weakness in this test.

## Current-Prompt UNL Selection

The current scoring prompt is the more important task layer.

| Metric on `scoring_v2` | Value |
|---|---:|
| Shared validators compared | 42 |
| Mean top-35 overlap | 35/35 |
| Top-35 symmetric difference | 0 |
| Candidate minus baseline mean score delta | -6.92 |
| Candidate max absolute validator-level mean delta | 12.8 |
| Spearman rank correlation | Not part of saved analysis; independent recomputation is approximately 0.80 depending on tie handling. |

Strict interpretation:

- The two models select the same top-35 UNL on this snapshot.
- qwen3.6 is not merely copying the baseline score scale. It is ranking similarly enough to preserve the current top-35, but scoring many validators lower.
- The lower qwen3.6 score scale is not automatically bad. It may be better if the desired behavior is stricter scoring of weak or incomplete validators.

## Penalty Calibration

The scoring task should punish poor consensus performance. This is one of the most important quality checks because a model that is too lenient can make the UNL boundary look healthier than the data supports.

Mean scores by 30-day agreement cohort:

| `scoring_v2` cohort | Qwen3-Next 80B A3B | qwen3.6 27B | Better if stricter penalties are desired |
|---|---:|---:|---|
| Strong, 30d >= 0.999 | 88.33 | 86.83 | Tie / baseline slightly higher |
| Marginal, 0.99 <= 30d < 0.999 | 87.10 | 79.62 | qwen3.6 |
| Weak, 30d < 0.99 | 75.00 | 65.58 | qwen3.6 |
| Failed, 30d <= 0.01 | 14.00 | 8.00 | qwen3.6 |
| Strong-minus-weak delta | 13.33 | 21.25 | qwen3.6 |
| Strong-minus-failed delta | 74.33 | 78.83 | qwen3.6 |

Strict interpretation: qwen3.6 is the harsher and more discriminating scorer on weak validators. If Dynamic UNL should strongly separate high-consensus validators from weak validators, qwen3.6 is better on this layer. If the policy preference is a more forgiving score scale from a single frozen snapshot, this layer is not automatically a qwen3.6 win.

The baseline is more forgiving. That may be desirable only if the governance preference is to avoid harsh penalties from a single frozen snapshot.

## Stability Across Repeated Runs

Cross-run score spread measures how much a model changes its score for the same validator across repeated OpenRouter calls at `temperature=0`.

| Layer | Model | Mean spread | Max spread | Validators over 10 spread |
|---|---|---:|---:|---:|
| `historical_v1` | Qwen3-Next 80B A3B | 3.48 | 8 | 0 |
| `historical_v1` | qwen3.6 27B | 1.90 | 5 | 0 |
| `scoring_v2` | Qwen3-Next 80B A3B | 6.31 | 15 | 4 |
| `scoring_v2` | qwen3.6 27B | 5.52 | 9 | 0 |

Strict interpretation:

- qwen3.6 has better worst-case stability on both prompt layers.
- On `scoring_v2`, qwen3.6 had no validator with spread above 10; the baseline had 4.
- This is OpenRouter-provider stability, not proof of self-hosted determinism. But within this comparison, qwen3.6 is not less stable.

## Reasoning Quality

Inline reasoning is what users and auditors will read. It is separate from hidden reasoning capability.

| Layer | Model | Mean reasoning chars | Numeric-evidence rate |
|---|---|---:|---:|
| `historical_v1` | Qwen3-Next 80B A3B | 160.9 | 96.7% |
| `historical_v1` | qwen3.6 27B | 119.5 | 92.9% |
| `scoring_v2` | Qwen3-Next 80B A3B | 150.1 | 83.8% |
| `scoring_v2` | qwen3.6 27B | 128.0 | 84.3% |

Strict interpretation:

- The baseline gives longer explanations.
- qwen3.6 gives shorter explanations.
- Numeric evidence rate is essentially tied on `scoring_v2`.
- Manual spot check found qwen3.6 occasionally used speculative cause language for missing geolocation. Example: it attributed null geolocation as "likely due to outdated IP resolution or privacy config". The input only proves null geolocation, not the cause.

Explanation-quality result: mixed.

The baseline is more verbose. qwen3.6 is slightly higher on numeric-evidence rate for `scoring_v2` by 0.5 percentage points. qwen3.6 also showed occasional speculative causal wording in manual review. The safest conclusion is that the baseline has a verbosity advantage, while qwen3.6 needs prompt tightening against causal speculation.

## Score Scale

qwen3.6 scores lower overall:

| Layer | Qwen3-Next 80B A3B mean score | qwen3.6 27B mean score | Candidate delta |
|---|---:|---:|---:|
| `historical_v1` | 84.62 | 80.45 | -4.13 |
| `scoring_v2` | 81.48 | 74.60 | -6.92 |

Strict interpretation:

- qwen3.6 is not calibrated to the same absolute score scale as the baseline.
- This does not make it lower quality by itself.
- If score thresholds are governance-significant, qwen3.6 would need calibration before scores are interpreted the same way.
- If only ranking/top-35 selection matters, the lower score scale is less important because the current top-35 stayed identical.

## What Does Not Matter For This Decision

The following are not quality reasons to reject qwen3.6:

- OpenRouter token price
- Modal monthly cost
- Whether the baseline was already tested first
- Whether qwen3.6 has not yet been deployed locally

Those are feasibility and operations questions. They can matter later, but they are not model-quality evidence.

## Deployment Side Note

qwen3.6 also has a practical deployment advantage, separate from the quality decision.

The selected self-hosted profile uses the official FP8 checkpoint `Qwen/Qwen3.6-27B-FP8` on a single H100. H100 is the right target for this checkpoint because it provides native FP8 Tensor Core support while using a smaller GPU class than the H200 currently used by the Qwen3-Next baseline.

The deployment evaluation now needs to confirm the operational facts under this chosen profile:

- full Dynamic UNL scoring prompt completion
- deterministic repeated outputs under SGLang
- schema compliance with the active `scoring_v2` contract

## Unweighted Quality Evidence

No subjective weights are applied here.

| Quality layer | Result | Evidence |
|---|---|---|
| External model quality | qwen3.6 wins | qwen3.6 leads every OpenRouter AA metric listed above. |
| Dynamic UNL schema compliance | Tie | Both models completed 5/5 runs on both prompt layers. |
| Current-prompt top-35 UNL selection | Tie | Same mean top-35 on `scoring_v2`. |
| Weak-validator discrimination | qwen3.6 wins if harsher consensus-failure penalties are desired | Strong-minus-weak delta is 21.25 for qwen3.6 vs 13.33 for baseline. |
| Failed-validator discrimination | qwen3.6 wins if harsher consensus-failure penalties are desired | Strong-minus-failed delta is 78.83 for qwen3.6 vs 74.33 for baseline. |
| Cross-run scoring stability | qwen3.6 wins | On `scoring_v2`, qwen3.6 max spread is 9 with 0 validators over 10; baseline max spread is 15 with 4 validators over 10. |
| Inline explanation quality | Mixed | Baseline explanations are longer; qwen3.6 has slightly higher `scoring_v2` numeric-evidence rate but occasional speculative wording. |
| Absolute score scale | Mixed | qwen3.6 scores lower overall; this is different calibration, not automatically better or worse. |

Strict count:

- qwen3.6 clear wins: 2
- qwen3.6 conditional wins under stricter consensus-penalty preference: 2
- baseline clear wins: 0
- ties: 2
- mixed: 2

This is why the quality-first conclusion favors qwen3.6 without relying on cost, deployment status, or prior selection history. The conclusion is strongest if Dynamic UNL wants stricter consensus-failure penalties, which is consistent with the scoring prompt's emphasis on consensus performance.

## Final Conclusion

If the goal is to choose the better model, not the cheapest model or the already-tested model, the evidence points to `qwen/qwen3.6-27b`.

The cleanest factual statement is:

`qwen/qwen3.6-27b` is the better quality model based on current evidence, assuming Dynamic UNL prefers stricter penalties for weak consensus performance. It should be prompt-tightened for explanation discipline and recalibrated if absolute score thresholds matter.

The next useful work is not another cost comparison. It is:

1. tighten the prompt against speculative causal wording
2. rerun qwen3.6 and the baseline on `scoring_v2`
3. compare whether qwen3.6 keeps stronger weak-validator separation while improving explanation discipline

## Sources

- Raw comparison outputs: `phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/`
- Analysis summary: `phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/analysis_summary.json`
- OpenRouter benchmark payload: `phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/openrouter_artificial_analysis_benchmarks.json`
- OpenRouter model metadata: `phase0/results/qwen36-27b-reevaluation/2026-04-29_qwen36-27b/openrouter_model_metadata.json`
- Qwen3.6 Hugging Face model card: `https://huggingface.co/Qwen/Qwen3.6-27B`
- Qwen3-Next Hugging Face model card: `https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct`
