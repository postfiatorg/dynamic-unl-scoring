# Model Candidate Evaluation — Qwen3.8-27B-FP8, Thinking Mode

Evaluation of `Qwen/Qwen3.8-27B-FP8` (revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`) as a candidate successor to the production scoring model `Qwen/Qwen3.6-27B-FP8`, this time with the model's reasoning ("thinking") mode enabled. Run 2026-08-20 against the same ten frozen scoring rounds as the non-thinking evaluation in [ModelCandidateQwen38.md](ModelCandidateQwen38.md), which concluded do-not-adopt on 2026-08-17. This evaluation asks the follow-up question that record left open: does letting the candidate reason before answering change its quality case? It changes no production configuration.

Deployment wrapper: `infra/deploy_qwen38_endpoint.py`, redeployed unchanged — Modal app `dynamic-unl-scoring-qwen38`, single H100, SGLang image `lmsysorg/sglang:nightly-dev-cu13-20260817-d91c3682` pinned by digest, `--enable-deterministic-inference`, `--disable-radix-cache` (the remediated profile the prior evaluation's determinism gate required), `--reasoning-parser qwen3`, no speculative algorithm, weights served from the retained `scoring-model-weights-qwen38` volume. Replay harness: `scripts/replay_model_candidate.py`, extended for this evaluation with request-contract overrides (`--enable-thinking`, `--max-tokens`), capture of the separated `reasoning_content` with its own SHA-256 fingerprint, `finish_reason` recording, and a `--mode-baseline` comparison path; every override is recorded in each run artifact's `request_overrides` field so deviations from the verbatim frozen request stay self-describing. Raw outputs: `docs/qwen38-thinking-replays/`; aggregated mechanical evidence: `docs/qwen38-thinking-replays/machine-checks.txt`.

## Request-contract deviations (stated up front)

The prior evaluation replayed each round's frozen `inputs/model_request.json` verbatim except the `model` field. Thinking mode cannot be tested under that contract, so this evaluation makes exactly two deliberate, recorded deviations per request:

1. **`chat_template_kwargs.enable_thinking` flipped to `true`.** Production requests carry `enable_thinking: false` (the non-thinking contract selected in the Phase 0 Qwen3.6 thinking comparison and inherited by every frozen request since). The override flips only this key; the rest of `extra_body` is preserved.
2. **`max_tokens` raised from the frozen 16,384 to 49,152.** The frozen budget is sized for non-thinking output and is factually insufficient for thinking mode: the Qwen3.6 thinking comparison consumed 16,397 completion tokens on a 42-validator round, already above the frozen cap, and round 18 carries 55 validators. 49,152 is three times the frozen budget, covering the ~3.4x completion-token multiplier observed on Qwen3.6 with headroom; the model's 262,144-token context (`text_config.max_position_embeddings`, HF revision `017b9c7a`) accommodates it trivially. `finish_reason` is recorded on every run so a silent truncation cannot pass as a valid response.

Because outputs under this contract differ from the published production responses by both a model change and a mode change, the committed non-thinking Qwen3.8 replays in `docs/qwen38-replays/` are used as a bridging baseline: candidate-vs-production isolates nothing, candidate-vs-`docs/qwen38-replays/` isolates thinking mode alone on the same model, same revision, same image, same frozen inputs.

## Decision criteria (stated before results)

Hard gates — any failure disqualifies the thinking-mode contract outright:

1. **Determinism.** Repeated runs of an identical overridden request must produce byte-identical responses — equal `content_sha256` **and** equal `reasoning_sha256` — under the deterministic serving profile, including across independently booted containers. A deterministic final answer above a divergent reasoning trace does not pass: the raw response is what sidecars must reproduce.
2. **Parse validity.** Every replayed response must parse completely under the unmodified production parser (`scoring_service/services/response_parser.py`) from `message.content`: all validators present, correct keys, valid dimension scores, zero errors, and no reasoning leakage into the final content.
3. **Deployability.** The pinned profile must serve full-size thinking-mode scoring requests on a single H100, and every run must finish with `finish_reason: stop` under the raised token budget — a `length` finish is a truncated scoring run, not a scoring run.

Additionally, before any thinking run is compared, a **setup control** must pass: a verbatim non-thinking replay of testnet round 18 against the redeployed endpoint must reproduce the prior evaluation's recorded fresh-path hash byte-for-byte, proving the redeployment is the same execution profile the prior record measured.

Comparison metrics — judged in aggregate, no single number decides:

4. **Sub-score plausibility.** Per-dimension drift against each round's published production response, read jointly with the mode-isolation drift against the non-thinking Qwen3.8 baseline, with attention to whether disagreements are evidence-defensible.
5. **Consistency.** Identical-evidence validators must score identically; sub-score banding behavior on prompt-v9+ rounds; whether thinking repairs or introduces the one evidence-twin violation the non-thinking candidate showed on round 18.
6. **Selection stability.** Final scores per each round's own era fed through the production selector with the round's frozen selector parameters must produce a UNL close to the published one, and the churn-gap calibration must remain valid under the thinking-mode score distribution.
7. **Qualitative evidence review.** A case-by-case reading of the highest-disagreement validators against their frozen evidence and the prompt rubric — including whether the visible reasoning trace actually adds decision value, which is the only thing thinking mode is for.

Cost and latency are recorded for operational planning and deliberately excluded from the quality verdict, with one exception already priced in by the Phase 0 Qwen3.6 comparison: a thinking contract multiplies every verifying sidecar's reproduction cost, so a quality tie does not favor it.

## Replay set

Identical to the non-thinking evaluation: testnet rounds 12–18 (prompt eras v5, v5, v6, v6, v8, v9, v9 — 42 to 55 validators) and devnet rounds 321, 323, 324 (v8, v9, v10 — 3 validators each). Determinism repeats (3x) run on testnet 18 (largest, current-era) and devnet 324 (v10); the remaining rounds run once. The runs executed on two concurrently booted containers; scheduling put the round 18 probe's three runs across both boots and all three devnet 324 runs on the same container — the Determinism section records exactly what each probe witnesses.

## Setup control (pass)

The verbatim non-thinking replay of testnet round 18 against the redeployed endpoint reproduced the prior evaluation's recorded fresh-path hash exactly: `40e01973…` (`t18_control_nonthinking.json`, 425 s including cold start and FP8-kernel JIT). Every thinking-mode difference below is therefore measured against a bit-confirmed re-instantiation of the profile the prior record measured.

## Determinism (gate 1: pass)

Both probes passed with three byte-identical runs each — equal `content_sha256` and `reasoning_sha256`: testnet 18 (content `e3b0c442…`, reasoning `6434715c…`) and devnet 324 (content `5de606f2…`, reasoning `91101ec5…`). The round 18 runs span the two independently booted containers, so its byte-stability — including the 47,205-character reasoning trace — is witnessed across boots; the devnet 324 runs were all served by one container, so its evidence is repeat-stability only. One scope limit follows and is recorded rather than glossed: because round 18 is the failure case, no committed artifact witnesses cross-boot bit-stability of a *successful, parseable* thinking response. On everything tested, the pinned profile is bit-exact under the thinking contract, reasoning traces included.

The t18 fingerprint is itself the evaluation's central finding: `e3b0c442…` is the SHA-256 of the **empty string**. The determinism gate passes while the response is unusable — three runs on two boots produced the identical failure, byte for byte. Determinism and validity are independent properties, and this evaluation separates them cleanly.

## Parse validity (gate 2: fail — 7/10, with both failures scale-dependent)

Seven rounds parse completely under the unmodified production parser with zero errors and no reasoning leakage into `message.content` (verified: no think-tags in any content). The three failures are exactly the three largest rounds — 51, 53, and 55 validators — and they are the current-era testnet rounds, the production-shaped workload:

- **Testnet 18 (55 validators, v9) and testnet 16 (51 validators, v8): deterministic early EOS inside the think block.** The model emits `finish_reason: stop` mid-reasoning — round 18 at 21,451 completion tokens (44% of the 49,152 budget), round 16 at 43,614 (89% of it), both `stop` rather than `length` — with `message.content` empty. The traces end mid-arithmetic (round 18 at validator 37 of 55, round 16 at validator 51 of 51, both cut inside a weighted-sum calculation). This is not truncation and not sampling noise: all three round-18 runs, on two boots, stop at the identical token.
- **Testnet 17 (53 validators, v9): reasoning bloat overruns any budget.** The model finishes its reasoning ("OK, let me write the final JSON now.", 95,405 trace characters), begins the final JSON, and hits `finish_reason: length` at the full 49,152 — three times the production budget — leaving the answer truncated mid-sentence. A still-larger budget might complete it at ~20+ minutes per request, but rounds 16 and 18 prove the failure family is not budget-bound.

Every round at or above 51 validators failed; every round at or below 50 passed. Candidate sets grow over time, so the thinking contract fails precisely in the direction production is heading. The non-thinking contract on the same model, same image, same inputs parses 10/10.

## Deployability (gate 3: fail on the same three rounds)

The profile deploys and serves full-size thinking requests (gate 3's serving half passes; DeepGEMM precompile remains broken for this model, as in the prior record, so each cold start pays FP8-kernel JIT inside its first request). But the `finish_reason: stop` requirement fails on testnet 17 (`length`) — and rounds 16/18, while nominally `stop`, stop without producing output, which is the same operational outcome. Where thinking does complete, it is heavy: successful 42–50-validator rounds took 425–499 s of pure inference against 93–108 s non-thinking, and the failing large rounds took up to 1,240 s before failing.

## Mechanical comparison (metrics 4–6, on the seven parseable rounds)

Per-round mean absolute sub-score deltas and selection outcomes (full tables in `machine-checks.txt`):

| Round | Prompt | n | vs production: c / r / s / d / i | sel Δ mean/max | UNL vs published | vs non-thinking Qwen3.8: c / r / s / d / i | seats vs non-thinking |
|---|---|---|---|---|---|---|---|
| t12 | v5 | 45 | 7.38 / 4.56 / 2.67 / 19.78 / 0.49 | 5.82 / 25 | 20/20 | 6.49 / 4.27 / 4.78 / 18.11 / 0.07 | 0 |
| t13 | v5 | 45 | 2.73 / 11.29 / 1.33 / 17.44 / 3.51 | 4.76 / 20 | 20/20 | 2.93 / 6.73 / 0.67 / 17.22 / 3.07 | 0 |
| t14 | v6 | 42 | 1.67 / 7.21 / 1.79 / 12.55 / 2.07 | 4.14 / 30 | 20/20 | 2.60 / 6.36 / 1.79 / 13.86 / 3.14 | 0 |
| t15 | v6 | 50 | 2.22 / 8.38 / 2.10 / 9.40 / 3.18 | 3.84 / 18 | 19/20 | 2.10 / 4.20 / 0.30 / 7.70 / 3.08 | 0 |
| d321 | v8 | 3 | 0.33 / 5.00 / 5.00 / 0.00 / 0.00 | 1.00 / 2 | 3/3 | 0.67 / 5.00 / 5.00 / 0.00 / 0.00 | 0 |
| d323 | v9 | 3 | 1.00 / 15.00 / 5.00 / 0.00 / 0.00 | 3.67 / 5 | 3/3 | 1.33 / 6.67 / 0.00 / 5.00 / 0.00 | 0 |
| d324 | v10 | 3 | 0.33 / 5.00 / 10.00 / 5.00 / 0.00 | 1.67 / 3 | 3/3 | 0.33 / 8.33 / 5.00 / 0.00 / 0.00 | 0 |

Readings:

- **Thinking never changes a UNL seat against the non-thinking candidate** — zero seats on all seven parseable rounds — while moving many individual sub-scores. This reproduces the Phase 0 Qwen3.6 result (same top-set, shifted calibration) on a second model generation.
- **Against production, selection matches seat-for-seat everywhere except the round 15 churn boundary** — a single seat at the same roll-sensitive 84-vs-85 boundary the prior evaluation documented on this round (detail in `machine-checks.txt`); evidence-fair, not an anomaly.
- **Diversity is again the widest surface** (9.4–19.8 vs production on testnet rounds; 7.7–18.1 in the mode-isolation comparison), confirming it as the noisiest dimension across both models and both modes.
- **The reliability spread on devnet 323 is the calibration warning.** Production scores all three validators r=95; thinking spreads them 75/80/85, ranked by the size of an old, resolved 30-day incident (58/50/24 missed ledgers out of ~850k, with clean 1h/24h windows). Score formula v1 weights reliability at 20% (`score_formula.py` WEIGHTS), so the worst validator's 20-point delta vs production alone moves its final by 4 points — above the production churn displacement gap of 3 (the round's observed max selection delta was 5 with the other sub-score drift included). Thinking-mode differentiation on stale noise is exactly the movement the gap calibration assumes cannot happen ("one band step moves a final by at most 1 point").
- **Evidence twins are not evaluable where they exist**: round 18 (the round carrying the prior evaluation's twin groups and its one non-thinking violation) produced no parseable thinking output, and round 15 — the largest parseable round — contains no exact-evidence twin groups. Banding on the parseable v9/v10 rounds is clean (non-consensus sub-scores on multiples of 5).

## Qualitative evidence review (metric 7)

The six named round-18 cases from the prior evaluation cannot be re-read: thinking mode produced no round-18 output, which is itself the qualitative headline. On the parseable rounds:

1. **Stale-tail reliability ranking (devnet 323, v9).** Thinking scores the three validators r=75/80/85, ranked by the size of an old resolved 30-day incident; production scores all three r=95. The v9 rubric text is genuinely ambiguous here: its band guidance places "an old, resolved incident" at 75–90 — which thinking follows literally, quoting the band in its trace — while production's 95 reads records this close to perfect (99.993%+ with clean recent windows) as the no-meaningful-losses branch. Neither placement violates the rubric. The concern is not the band choice but the ranking *within* the band by stale tail size (58 vs 50 vs 24 missed ledgers out of ~850k): differentiation on noise that, at 20% weight, moves a final by up to 4 points against a churn gap of 3. Split on the band; the calibration risk stands either way.
2. **Software shaved below the top band on current versions (devnet 324, v10).** All three validators run the current 1.0.4; thinking writes "consistent 1.0.4 software" and scores s=90. The number contradicts its own text — the same prose-number mismatch pathology the prior evaluation found in non-thinking sub-scores, unrepaired by reasoning. Production better.
3. **Currently-offline validators (testnet 15, v6).** For three validators with 1h agreement at zero, production gave reliability 85 with consensus 10; thinking gives reliability 40–50. Thinking's harsher operational read of a currently-down validator is at least as defensible under any era's rubric. Thinking slightly better, on a retired prompt era.
4. **Outdated-software validator on DigitalOcean (testnet 15).** Thinking (50/50/45/50/50) is stricter than production (80/60/80/65/45) on a validator with a genuinely bad 24-hour window (89.41%) and 1.0.0 software; directionally reasonable, magnitude aggressive for the v6 era that consumed the model's overall directly.
5. **Where the failing traces die.** Both early-EOS failures stop inside a manual weighted-sum arithmetic block — computing each validator's overall score under weights the model invented (0.35/0.25/0.15/0.15/0.10, appearing in both failing traces), which match neither the prompt's instruction (a holistic advisory judgment, no weights prescribed) nor score formula v1's authoritative 50/20/10/10/10. Round 18 cuts mid-sum at validator 37 of 55; round 16 completes validator 51's sum and stops before rounding it. The parseable rounds' traces estimate overalls holistically instead and survive. On v9+ rounds the overall is advisory only — the pipeline recomputes the final deterministically — so the arithmetic that kills the large rounds produces a number the pipeline discards even when it completes. The traces are clear and readable; they are simply not producing decisions the pipeline uses.

Overall qualitative verdict: where thinking parses, it is an in-family scorer whose disagreements with production are mostly the same surfaces the non-thinking candidate showed (diversity drift, sub-top software bands, prose-number mismatches), plus a new stale-noise reliability spread that presses against the churn-gap calibration. Nothing in the review found a case on a current prompt era where thinking corrects a production error.

## Sidecar and contract implications (recorded for completeness)

Mechanically, a thinking contract would travel the normal route: `enable_thinking: true` and the raised `max_tokens` inside each round's frozen `inputs/model_request.json`, the manifest unchanged in its `code.*` hashes, sidecars replaying the frozen request verbatim as today. But every verifying sidecar would pay the 3–4x inference cost per reproduction, RAW-level convergence would then cover multi-tens-of-KB reasoning traces (a much larger byte surface that must reproduce exactly — which this evaluation shows it does, on this image, when generation completes at all), and the final bundles would grow accordingly. Moot under the gate failures, but worth recording: none of these were the blocker.

## Cost and latency (excluded from the verdict)

Fifteen inference calls (one non-thinking control, ten thinking sweep runs, four thinking repeats) totalled 1.95 hours of summed request time across two H100 containers; with cold starts, JIT (no working DeepGEMM precompile), and scaledown windows the billed footprint is roughly 2.5–3 H100-hours on the `agti` workspace. Successful thinking rounds ran 3.9–5.3x their non-thinking counterparts (t12–t15: 425–499 s vs 93–108 s recorded in the prior evaluation's artifacts); the failing rounds were not cheap either — ~443 s per empty round-18 attempt, 1,046 s for round 16, and 1,240 s for round 17. After the runs the Modal app was stopped; the weights volume (`scoring-model-weights-qwen38`) is retained.

## Conclusion

**Do not adopt the thinking-mode contract. The non-thinking do-not-adopt from [ModelCandidateQwen38.md](ModelCandidateQwen38.md) stands unchanged.**

- The decisive reason is a hard gate failure, not a judgment call: thinking mode produces no parseable output on any round of 51+ validators — deterministic early EOS inside the reasoning block on two rounds, budget-unbounded reasoning bloat on the third — and parses only at sizes production has already outgrown on testnet. The failure worsens with exactly the variable that grows.
- Where it works, it adds nothing the pipeline uses: zero UNL seats changed against the non-thinking candidate on all seven parseable rounds, the reasoning budget spent re-deriving the advisory overall score that formula v1 already computes deterministically, and the qualitative disagreements either repeat the non-thinking candidate's known drift or introduce new stale-noise reliability spreads that press against the churn-gap calibration.
- Determinism — the gate a reasoning trace would be expected to threaten — is the one thing that held on everything tested: bit-exact content and reasoning on every probe, across boots for the round 18 failure case and across same-container repeats for the parseable devnet 324 case. The reproducibility machinery is not the obstacle; generation robustness at production scale is. That extends the prior record's conclusion that this architecture's inference surface is young: the cache-hit path was the gap the non-thinking evaluation found, and think-block termination at scale is the gap this one finds.
- If thinking mode is ever reconsidered — for this model family or a successor — the starting point is this record's failure signatures (early think-block EOS at 51+ validators on the pinned image; reasoning bloat past 3x budget) re-tested on a newer runtime image, and the natural venue is the standing governance process, where the exam-and-judge machinery can grade a thinking contract against the incumbent without a bespoke side-by-side.

The evaluation deliberately leaves production untouched: the incumbent (`Qwen3.6-27B-FP8`, April image, precompiled, cache-on, non-thinking) remains the scoring model on both environments.
