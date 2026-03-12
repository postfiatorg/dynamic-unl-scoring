# Strategic Model Assessment: 8-Run Session `2026-03-10_15-00-16`

This report evaluates the newest 8-run benchmark session in `results/2026-03-10_15-00-16`, but it does **not** treat that session as the only decision input.

Dynamic UNL is not just a “return valid JSON from OpenRouter” problem. The production system described in `postfiatd` is a deterministic, single-prompt, whole-validator-set scoring pipeline that later feeds commit-reveal, convergence monitoring, and eventually authoritative UNL selection. Because of that, this assessment uses the latest benchmark results as one input inside a broader production-oriented framework.

## Executive Conclusion

**Recommended primary candidate:** `qwen3-235b-thinking`

**Recommended challenger:** `minimax-m2.5`

**Recommended control / fallback:** `qwen3-235b-instruct`

Why:

- The current benchmark snapshot is narrower than the future scoring problem. It is dominated by agreement history, while future rounds will add richer identity, ASN/provider, and per-validator geolocation signals.
- The latest 8-run session shows that all three models are already close on the final averaged 35-validator selection. The choice is therefore less about a different current list and more about future scoring philosophy, cutoff behavior, and long-horizon fit.
- `qwen3-235b-thinking` is the strongest strategic choice because it has the best reasoning headroom among the H200-compatible Qwen variants, it completed all 8 runs, and it applies a stricter and more production-useful penalty curve to historically weak validators.
- `minimax-m2.5` remains a serious candidate because its boundary behavior is excellent and its instruction-following prior is strong, but the 8-run session still includes one hard provider-side failure.
- `qwen3-235b-instruct` produced the cleanest current benchmark artifacts, but it was also the most lenient near the UNL cutoff and the least strategically interesting once future data richness is considered.

## Important Framing

This report intentionally separates two questions:

1. Which model produced the tidiest OpenRouter benchmark artifacts today?
2. Which model is the best strategic fit for Dynamic UNL as designed in `Design.md` and `ImplementationPlan.md`?

Those are not the same decision.

Latency and token spend are deliberately treated as secondary here. The design assumes periodic scoring rounds, deterministic inference overhead is explicitly acceptable, and the harder problem is long-horizon convergence and selection quality.

The design requires:

- one deterministic prompt over the whole validator set,
- temperature 0 and structured JSON,
- later validator-side replay with the same model, prompt, and data,
- convergence analysis at exact-output, score-level, and UNL-level,
- churn control near the 35-validator cutoff,
- eventual transition to validator-converged UNL authority.

The implementation plan also makes an important distinction:

- Phase 1 does **not** require determinism; only the foundation scores.
- Phase 2 is gated by a reproducibility harness and high output equality on the mandatory GPU type.

That means OpenRouter jitter is informative, but it is **not** the final determinism verdict for any model.

## Current OpenRouter Readout

If the decision were limited to the current OpenRouter benchmark session only, the ranking would be:

| Rank | Model | Reason |
|------|-------|--------|
| 1 | `qwen3-235b-instruct` | Cleanest complete-run record and best score stability |
| 2 | `qwen3-235b-thinking` | Clean record, stronger scoring philosophy, but higher drift |
| 3 | `minimax-m2.5` | Strong complete runs, but one provider-side failure in this session |

That is a useful operational readout, but it is not the right final selection framework for Dynamic UNL.

## Strategic Ranking

This is the ranking I would use for later development.

| Rank | Model | Strategic Score | Recommended Role |
|------|-------|-----------------|------------------|
| 1 | `qwen3-235b-thinking` | **86/100** | Primary candidate |
| 2 | `minimax-m2.5` | **82/100** | Main challenger |
| 3 | `qwen3-235b-instruct` | **73/100** | Control / fallback |

## Strategic Scorecard

Weights:

- Future-task headroom: 25
- Phase 1-3 convergence proxy: 25
- Churn-control and boundary behavior: 20
- Rubric fidelity and penalty calibration: 20
- Artifact discipline and auditability: 10

| Model | Headroom (25) | Convergence Proxy (25) | Boundary Behavior (20) | Calibration (20) | Artifact Discipline (10) | Overall (100) |
|------|----------------|------------------------|------------------------|------------------|--------------------------|---------------|
| `qwen3-235b-thinking` | 24 | 19 | 17 | 18 | 8 | **86** |
| `minimax-m2.5` | 23 | 18 | 20 | 15 | 6 | **82** |
| `qwen3-235b-instruct` | 16 | 24 | 13 | 11 | 9 | **73** |

Interpretation:

- `qwen3-235b-thinking` wins because the broader Dynamic UNL problem is more demanding than the current benchmark snapshot, and its scoring behavior is the most aligned with a serious whole-network selection task.
- `minimax-m2.5` comes second because it combines strong future-task priors with the sharpest cutoff behavior, but its one failed run prevents a first-place recommendation today.
- `qwen3-235b-instruct` comes third not because it is unusable, but because its current strength is mostly “safe benchmark hygiene,” while its boundary and calibration behavior are the least aligned with the larger system design.

## Why The Broader Framework Matters

The current snapshot under-exercises several parts of the future scoring problem:

- All validators are on server version `3.0.0`, so software diligence is barely tested.
- The benchmark does not yet provide per-validator MaxMind geolocation, which the production design expects.
- The future pipeline will also ingest ASN/provider concentration and on-chain identity records.
- The future plan explicitly adds KYC/KYB-derived identity boosts to validator profiles.

In other words, today’s benchmark mostly tests:

- agreement-history reasoning,
- domain / identity hints,
- basic JSON schema discipline.

That is valuable, but it is not the whole Dynamic UNL task.

Model priors from `docs/phase0/ModelBenchmarkRound1.md` therefore still matter:

| Model | Reasoning Prior | Instruction-Following Prior |
|------|------------------|-----------------------------|
| `qwen3-235b-thinking` | 59.40 | 40.64 |
| `minimax-m2.5` | 59.30 | 57.23 |
| `qwen3-235b-instruct` | 58.43 | 21.72 |

The gap is especially important for `qwen3-235b-instruct`: it has the weakest prior profile of the three on the dimensions that matter once the snapshot becomes richer and less dominated by raw agreement.

## What The 8 Runs Actually Show

### 1. All three models are already close on the final averaged selection

When complete runs are averaged by model, the top-35 selection is identical across all three models.

That means the model decision is not about three radically different UNLs today. It is mainly about:

- how decisively the model treats borderline validators,
- how much score compression it introduces near the cutoff,
- how much future signal complexity it is likely to absorb well,
- and how likely it is to survive the later convergence and replay architecture.

### 2. None of these OpenRouter runs should be mistaken for Phase 2 determinism proof

Across the complete runs:

- exact score-map equality was zero for all three models,
- exact-output equality therefore remains unproven for all three,
- and the real determinism gate still belongs to the later SGLang/H200 reproducibility harness.

This matters because `ImplementationPlan.md` explicitly treats that harness as the hard gate for Phase 2, not these provider-mediated benchmark runs.

### 3. The biggest real difference is boundary behavior

This is where the models separate most clearly:

- `minimax-m2.5` produces the smallest borderline pool.
- `qwen3-235b-thinking` is harsher on weak historical performers.
- `qwen3-235b-instruct` rotates the largest number of near-cutoff validators in and out of the top 35.

For a system that later adds churn control and validator-converged authority, that matters more than benchmark neatness.

## Empirical 8-Run Metrics

### Convergence Proxy

| Model | Complete Runs | Pairwise UNL Exact Match Rate | Avg UNL Overlap | Avg Pairwise Scores Within ±5 | Avg Rank Spearman |
|------|---------------|-------------------------------|-----------------|-------------------------------|-------------------|
| `qwen3-235b-thinking` | 8/8 | 32.1% | 34.18 / 35 | 67.7% | 0.7947 |
| `minimax-m2.5` | 7/8 | 42.9% | 34.43 / 35 | 72.8% | 0.8224 |
| `qwen3-235b-instruct` | 8/8 | 35.7% | 34.11 / 35 | 89.1% | 0.8752 |

What this means:

- `qwen3-235b-instruct` is the most numerically stable in the benchmark environment.
- `minimax-m2.5` is better than it first appears if we look at UNL-level overlap rather than only the one failed run.
- `qwen3-235b-thinking` is the least stable numerically, but still structurally complete across all 8 runs.

This table is why `qwen3-235b-instruct` remains the best **benchmark control**, even though it is not the best **strategic selection**.

### Boundary And Churn Behavior

| Model | Always In Top 35 | Ever In Top 35 | Borderline Pool | Avg Cutoff Gap |
|------|------------------|----------------|-----------------|----------------|
| `qwen3-235b-thinking` | 33 | 37 | 4 | 2.75 |
| `minimax-m2.5` | 34 | 36 | 2 | 4.00 |
| `qwen3-235b-instruct` | 31 | 37 | 6 | 2.38 |

Interpretation:

- `minimax-m2.5` is the most decisive at the boundary.
- `qwen3-235b-thinking` is materially better than instruct on borderline pool size.
- `qwen3-235b-instruct` is the most oscillatory near the cutoff.

For Dynamic UNL, smaller borderline pools are valuable because the design later adds churn control and ultimately relies on validator convergence around the same 35-validator set.

### Rubric Fidelity And Penalty Calibration

The prompt says:

- `>99.9%` agreement is expected,
- `<99%` is a serious issue,
- and low scores should be reserved for clearly weak validators.

Average score assigned to validators below key 30-day agreement thresholds:

| Model | Avg Score For `<0.99` Cohort | Avg Score For `<0.97` Cohort |
|------|-------------------------------|-------------------------------|
| `qwen3-235b-thinking` | 56.16 | 44.57 |
| `minimax-m2.5` | 59.19 | 49.18 |
| `qwen3-235b-instruct` | 66.58 | 56.59 |

This is the clearest argument against ranking `qwen3-235b-instruct` first strategically.

It is the model most likely to keep historically weak validators in a relatively comfortable score band. That is useful if the goal is score smoothness. It is not ideal if the goal is a more decisive and future-ready UNL selection system.

## Diversity And Future-Signal Readiness

Another important finding from the 8 runs:

- explicit diversity references were rare for all three models,
- and the benchmark does not yet force a strong test of per-validator geography / ASN / provider concentration,
- so none of the models can claim a proven lead on that dimension from this session alone.

That is exactly why the capability priors still matter.

If the benchmark had already included:

- per-validator GeoIP context,
- richer ASN / hosting-provider concentration,
- on-chain identity records,
- KYC / KYB verification state,
- and more operator-clustering evidence,

then I would be more willing to let the benchmark readout dominate the strategic choice.

We are not there yet.

## Model-by-Model Assessment

### `qwen3-235b-thinking`

Why it ranks first:

- Strongest strategic headroom for a richer future scoring packet
- 8/8 complete runs in the latest session
- Best serious-issue calibration of the three
- Smaller borderline pool than instruct
- Same Qwen family as instruct, which preserves a clean fallback path

Why it is not an effortless choice:

- It shows more run-to-run score drift than instruct
- Its OpenRouter benchmark behavior does not prove later deterministic convergence

Conclusion:

This is the best model to advance as the primary Dynamic UNL candidate, with the understanding that it must next survive local deterministic inference testing.

### `minimax-m2.5`

Why it ranks second:

- Strong reasoning and instruction-following prior profile
- Best cutoff decisiveness in the 8-run session
- Very compact borderline pool
- Its complete runs converge semantically better than a simple “7/8 complete” reading suggests

Why it is not first:

- It is still the only model with a hard failed run in the latest session
- That failure appears to be a provider / execution-path failure rather than a bad scoring philosophy, but it is still a real reliability penalty

Conclusion:

This remains the best challenger to the Qwen path and deserves local-inference validation, but it does not yet have enough evidence to take first place.

### `qwen3-235b-instruct`

Why it ranks third:

- Cleanest current benchmark behavior
- Best score-level stability in the latest session
- Most useful control model for future comparisons

Why it does not rank higher:

- It has the weakest future-task prior profile of the three
- It is the most lenient near the cutoff
- It produces the largest borderline pool
- It reacts least aggressively to validators that already look historically weak by the benchmark’s own rubric

Conclusion:

Keep it as the control and fallback model, but do not let its current OpenRouter neatness overrule the broader Dynamic UNL design requirements.

## Recommended Development Path

1. Advance `qwen3-235b-thinking` as the primary candidate into local SGLang / RunPod validation.
2. Carry `minimax-m2.5` as the main challenger into the same local-inference checks.
3. Keep `qwen3-235b-instruct` in the repo as the control model and fallback path.
4. Before locking the final choice, run a richer benchmark round that includes stronger identity, ASN/provider, and per-validator geographic context.

## Bottom Line

If the task were only “which model returns the cleanest benchmark artifacts today,” the answer would be `qwen3-235b-instruct`.

That is too narrow for Dynamic UNL.

For the system described in `Design.md` and `ImplementationPlan.md`, the better strategic answer is:

1. `qwen3-235b-thinking`
2. `minimax-m2.5`
3. `qwen3-235b-instruct`
