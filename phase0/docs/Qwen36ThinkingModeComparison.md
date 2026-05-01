# Qwen3.6 Thinking vs Non-Thinking: Dynamic UNL Scoring

Date: 2026-04-30

Model: `Qwen/Qwen3.6-27B-FP8`

Endpoint profile: Modal/SGLang, H100, deterministic inference, pinned `dev-cu13` SGLang image

Compared prompt layer: `scoring_v2`

## Recommendation

Use **non-thinking mode** as the Dynamic UNL production default.

Thinking mode is technically viable: it produced valid JSON, no final-answer reasoning leakage, deterministic repeated outputs, and the same top-35 validator set as non-thinking mode. However, it did not improve the actual UNL selection decision. It made the run about 4x slower, generated about 3.4x more completion tokens, and introduced wider internal calibration shifts across sub-scores.

Thinking mode is useful as a diagnostic or research mode when investigating borderline validators or prompt calibration. It is not the better default for recurring Dynamic UNL scoring.

## Test Artifacts

| Mode | Results folder | Runs |
|---|---|---:|
| Non-thinking | `phase0/results/modal/qwen36-27b-fp8/2026-04-30_qwen36-27b-fp8_scoring-v2/` | 5 |
| Thinking | `phase0/results/modal/qwen36-27b-fp8-thinking/2026-04-30_qwen36-27b-fp8-thinking_scoring-v2/` | 5 |

Both runs used the same deployed Modal endpoint and the same `scoring_v2` prompt. The only meaningful request difference was that non-thinking passed `chat_template_kwargs.enable_thinking=false`, while thinking mode omitted that override.

## Parseability

Thinking mode is easy to parse with the current scoring utilities.

| Check | Non-thinking | Thinking |
|---|---:|---:|
| Final JSON in `message.content` | yes | yes |
| Thinking separated into `reasoning_content` | none emitted | yes |
| JSON-valid runs | 5/5 | 5/5 |
| Complete validator result sets | 5/5 | 5/5 |
| `network_summary` present | 5/5 | 5/5 |
| Invalid `scoring_v2` dimension fields | 0 | 0 |
| Extraction code change needed | no | no |

This matters because thinking mode did not corrupt the final answer. SGLang's `qwen3` reasoning parser separated the hidden reasoning from the final JSON response as intended.

## Determinism

Both modes passed the determinism gate.

| Check | Non-thinking | Thinking |
|---|---:|---:|
| Unique extracted-answer hashes across 5 runs | 1 | 1 |
| Unique score-map hashes across 5 runs | 1 | 1 |
| Unique top-35 hashes across 5 runs | 1 | 1 |
| Validators with score spread across runs | 0 | 0 |
| Maximum score spread across runs | 0 | 0 |
| Top-35 intersection across 5 runs | 35/35 | 35/35 |

This means thinking mode is not rejected for reproducibility. It is deterministic under the current Modal/SGLang profile.

## Runtime Cost

Thinking mode is much heavier.

| Metric | Non-thinking | Thinking | Impact |
|---|---:|---:|---:|
| Mean elapsed time | 87.99s | 356.92s | 4.1x slower |
| Prompt tokens | 7,654 | 7,652 | same |
| Completion tokens | 4,774 | 16,397 | 3.4x more |
| Total tokens | 12,428 | 24,049 | 1.9x more |
| Captured JSON size per run | ~76 KB | ~132 KB | 1.7x larger |
| `reasoning_content` length | 0 chars | 27,788 chars | large hidden trace |

For the current 42-validator snapshot this is operationally tolerable. For a future 500-validator run, thinking mode is the bigger scaling risk. If output size scaled roughly linearly, thinking mode would push far beyond the current 50k output-token budget, while non-thinking mode is much closer to the expected production shape.

## Decision Output

The top-35 validator set is identical.

| Comparison | Result |
|---|---|
| Common validators scored | 42 |
| Mean score delta, thinking minus non-thinking | +0.10 |
| Mean absolute score delta | 2.52 |
| Max absolute score delta | 10 |
| Validators with changed overall score | 35/42 |
| Top-35 overlap | 35/35 |
| Top-35 membership change | none |

This is the central result: thinking changes many individual scores slightly, but it does not change the selected validator set.

## Score Calibration

Thinking mode changes the sub-score calibration in a systematic way.

| Dimension | Mean delta, thinking minus non-thinking | Interpretation |
|---|---:|---|
| `consensus` | -2.33 | slightly stricter on consensus sub-score |
| `reliability` | +20.00 | much more generous reliability sub-scores |
| `software` | -5.00 | slightly lower despite all validators running version `3.0.0` |
| `diversity` | +20.00 | less punitive for null ASN/country data |
| `identity` | +21.43 | much more generous identity sub-scores |

Some of this is defensible. The prompt says identity verification is not deployed on testnet and should be treated as neutral. It also says null ASN/country should be penalized as an infrastructure transparency risk. Thinking mode appears to interpret those missing-data cases as more neutral than non-thinking mode.

The problem is that thinking mode is sometimes too generous on dimensions that should remain penalties. For example, a near-offline validator still received high reliability and identity sub-scores in thinking mode, even though its final overall score stayed low because consensus dominated. That makes the final UNL decision acceptable, but the explanatory sub-scores less crisp.

## Notable Validator Effects

| Validator | Non-thinking score | Thinking score | Delta | Notes |
|---|---:|---:|---:|---|
| `v006` | 5 | 15 | +10 | Still rejected, but thinking mode is less severe on an effectively offline validator. |
| `v010` | 5 | 12 | +7 | Same pattern as `v006`; still outside selection. |
| `v036` | 45 | 55 | +10 | Verified domain helps, but 84.8% 30-day agreement remains a serious reliability issue. |
| `v035` | 60 | 68 | +8 | Thinking mode gives more credit despite degraded long-term consensus. |
| `v002`, `v016`, `v032`, `v038`, `v039` | unchanged at top | unchanged at top | 0 | Top trusted validators remain stable. |

The changes are not random. Thinking mode mostly raises weak or metadata-limited validators while slightly lowering many healthy validators by 1-3 points. Because the strongest validators remain strong and the weakest validators remain below the cutoff, the selected set stays identical.

## What Thinking Mode Is Better At

Thinking mode is better for inspection and debugging.

- It exposes a separated `reasoning_content` field that shows how the model reasoned through the network.
- It produced a coherent final `network_summary`.
- It may help diagnose prompt ambiguity around missing ASN/country, identity neutrality, and domain verification.
- It can be useful for one-off reviews of borderline validators where the operator wants more trace context.

These are research advantages, not production scoring advantages.

## What Non-Thinking Mode Is Better At

Non-thinking mode is better for the recurring Dynamic UNL job.

- It produces the same top-35 set.
- It is deterministic.
- It is much faster.
- It uses far fewer output tokens.
- It avoids storing large hidden reasoning traces.
- It is easier to scale to larger validator sets.
- Its sub-scores are more conservative on missing infrastructure and identity data, which is appropriate for a network trust list.

The Dynamic UNL scoring task needs stable validator decisions more than it needs long internal deliberation. On this data, thinking mode does not change the decision.

## Final Decision

Winner: **non-thinking mode**.

Thinking mode passes the technical feasibility test, so it remains a valid optional mode. It should not be the production default unless a future dataset shows a real decision-quality improvement, such as better handling of borderline validators or a more defensible top-35 set.

For now, use Qwen3.6 FP8 on Modal/SGLang with thinking disabled for production-shaped Dynamic UNL scoring. Use thinking mode only for calibration studies or manual review.
