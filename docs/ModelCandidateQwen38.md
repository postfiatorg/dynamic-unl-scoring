# Model Candidate Evaluation — Qwen3.8-27B-FP8

Evaluation of `Qwen/Qwen3.8-27B-FP8` (revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`, published 2026-08-14, Apache 2.0, official vendor FP8 build) as a candidate successor to the production scoring model `Qwen/Qwen3.6-27B-FP8` (revision `e89b16ebf1988b3d6befa7de50abc2d76f26eb09`). Run 2026-08-17 against real frozen scoring rounds. This evaluation changes no production configuration; the adopt/don't-adopt decision and any rollout are separate, subsequent work.

Deployment wrapper: `infra/deploy_qwen38_endpoint.py` (Modal app `dynamic-unl-scoring-qwen38`, single H100, SGLang image `lmsysorg/sglang:nightly-dev-cu13-20260817-d91c3682@sha256:fa8774dd128600a09fd6d46670b06fb69a55dac8a3881e50ccf0916a45eb39af` — the production image family's first build carrying SGLang's day-0 Qwen3.8 support — deterministic profile, `--enable-deterministic-inference`, no speculative algorithm configured so the model's MTP head is unused, thinking disabled through the same `chat_template_kwargs.enable_thinking=false` mechanism the incumbent uses). Replay harness: `scripts/replay_model_candidate.py`, which replays each round's frozen `inputs/model_request.json` verbatim except the `model` field, so every output difference is attributable to the model alone. Raw outputs with determinism fingerprints: `docs/qwen38-replays/`; the aggregated mechanical evidence is `docs/qwen38-replays/machine-checks.txt`.

## Decision criteria (stated before results)

Hard gates — any failure disqualifies the candidate outright:

1. **Determinism.** Repeated runs of an identical frozen request must produce byte-identical responses (equal `content_sha256`) under the deterministic serving profile.
2. **Parse validity.** Every replayed response must parse completely under the unmodified production parser (`scoring_service/services/response_parser.py`): all validators present, correct keys, valid dimension scores, zero errors.
3. **Deployability.** The pinned profile must deploy, serve, and answer full-size scoring requests on a single H100.

Comparison metrics — judged in aggregate, no single number decides:

4. **Sub-score plausibility.** Per-dimension drift against each round's published production response, with attention to whether disagreements are evidence-defensible rather than merely small.
5. **Consistency.** Identical-evidence validators must score identically; dominance ordering checked on clear pairs; sub-score banding behavior on prompt-v9+ rounds.
6. **Selection stability.** Final scores (per each round's own era: score formula v1 where the round pinned it, model overall score before that) fed through the production selector with the round's frozen selector parameters must produce a UNL close to the published one, with any seat difference explainable from the scores; the churn-gap calibration must remain valid under the candidate's score distribution.
7. **Qualitative evidence review.** A case-by-case reading of representative validators — judged against the frozen evidence, the way testnet round 16 was audited in `ScoringPromptV9.md` — asking which model's judgment better reflects the evidence and the prompt rubric, including the quality of the written reasoning.

Cost and latency are recorded for operational planning and deliberately excluded from the quality verdict.

## Replay set

The ten most recent completed rounds with frozen input packages: testnet rounds 12–18 (prompt eras v5, v5, v6, v6, v8, v9, v9 — 42 to 55 validators each) and devnet rounds 321, 323, 324 (v8, v9, v10 — 3 validators each; 324 is the only production round under prompt v10). Testnet rounds 9–11 predate the frozen-input-package contract on testnet and are therefore not replayable — this is why the set extends to devnet rather than further back on testnet. Determinism repeats (3×) ran on testnet 18 (largest, current-era) and devnet 324 (v10); the remaining rounds ran once.

## Deployability findings (gate 3: pass, with two profile differences)

Two incumbent-profile elements do not carry over to the candidate; both are recorded in the wrapper with comments:

- **DeepGEMM precompile fails.** The image-build step `python3 -m sglang.compile_deep_gemm` (baked into the incumbent's image so cold starts skip FP8-kernel JIT) exits 1 against this model on the 20260817 image. It is a kernel warm-up only, so the candidate profile sets `SCORING_COMPILE_DEEPGEMM=0` and accepts a slower first request. If the model is ever adopted, restoring a working precompile (or an in-image warm-up request) is the follow-up that recovers incumbent-class cold starts.
- **The prefix-cache-hit path is not deterministic-mode-covered** (next section), so the profile sets `SCORING_DISABLE_RADIX_CACHE=1` through the new env-gated pass-through in `infra/deploy_endpoint.py` (default off; the production wrapper is unaffected).

With those two settings the pinned profile deploys, serves, and answers full-size scoring requests on a single H100. Gate 3 passes.

## Determinism (gate 1: fail on the default profile; pass with the radix cache disabled)

On the default profile (radix cache enabled, as production runs the incumbent), the gate **failed** with a precise structure: for both probed rounds, the *first* execution of a request produced one output and every repeat produced a different, then-stable output — testnet 18: `40e01973…` first, `b6ceaf8b…` on repeats; devnet 324: `e3c2ddc9…` first, `db1a2764…` on repeats. The two variants of round 18 differ in 42 of 275 sub-score cells (one- and two-band steps of 5–10 points, confined to reliability and diversity; consensus, software, and identity untouched), moving 21 of 55 formula finals by 1–2 points; the round 324 variants differ in reasoning prose only.

Characterization across two independent cold boots proved there is **no randomness anywhere**: every hash reproduced exactly, including the first-after-boot output and even the sequence-position output of a request run after a particular request history. The model is fully deterministic *as a function of request history since boot*. The divergence is the prefix-cache: a cache-hit repeat computes down a different kernel path than a fresh prefill, and on this image the hybrid-architecture cache-hit path is not covered by `--enable-deterministic-inference` (the incumbent's paths agree on its April image, which is precisely what phase 0, the governance exam validations, and every sealed sidecar round have relied on).

The remediation follows from the diagnosis: `--disable-radix-cache` forces every request down the fresh-prefill path — which is also exactly production topology, where each round's request runs once against a cold-started endpoint and there is never a cache to hit. On the remediated profile the gate **passes**: three runs of round 18 all `40e01973…`, three runs of round 324 all `e3c2ddc9…`, byte-identical, and equal to the fresh-path outputs observed on the default profile across independent boots. Disabling the cache costs this workload nothing (one request per boot, no shared prefixes; warm repeat latency moved ~118s → ~131s in the replay setting only).

The gate as pre-stated is failed by the default profile and passed by the remediated one. Every comparison below uses fresh-prefill-path outputs: for rounds 18 and 324 this is verifiable from the artifacts (the `*_norad` hashes equal the fresh-path hashes reproduced across boots), and the eight single-run sweep rounds were executed against the radix-disabled deployment, which was the only profile live at that point in the run sequence. Run artifacts produced after this evaluation additionally carry `endpoint` and `requested_at` fields so profile attribution no longer rests on execution order.

## Mechanical comparison (gates 2, metrics 4–6)

**Parse validity: 10/10 rounds parse completely** under the production parser — including the v5/v6-era requests — with zero errors and no key corruption. Gate 2 passes.

Per-round mean absolute sub-score deltas against the published production response, and selection outcomes (full table in `machine-checks.txt`):

| Round | Prompt | n | consensus | reliability | software | diversity | identity | selection Δ mean/max | UNL vs published |
|---|---|---|---|---|---|---|---|---|---|
| t12 | v5 | 45 | 2.36 | 5.93 | 7.44 | 3.67 | 0.56 | 3.29 / 25 | 20/20 |
| t13 | v5 | 45 | 1.36 | 5.22 | 2.00 | 1.78 | 0.67 | 5.00 / 15 | 20/20 |
| t14 | v6 | 42 | 2.02 | 2.05 | 3.57 | 4.17 | 1.31 | 6.38 / 27 | 20/20 |
| t15 | v6 | 50 | 2.60 | 5.42 | 2.40 | 3.30 | 0.50 | 2.94 / 20 | 19/20 |
| t16 | v8 | 51 | 2.39 | 5.20 | 6.47 | 8.73 | 0.29 | 2.04 / 20 | 20/20 |
| t17 | v9 | 53 | 0.00 | 3.87 | 1.13 | 7.36 | 0.19 | 1.77 / 6 | 19/20 |
| t18 | v9 | 55 | 0.22 | 4.36 | 1.09 | 9.27 | 0.00 | 1.60 / 4 | 20/20 |
| d321 | v8 | 3 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.67 / 1 | 3/3 |
| d323 | v9 | 3 | 0.33 | 8.33 | 5.00 | 5.00 | 0.00 | 1.33 / 2 | 3/3 |
| d324 | v10 | 3 | 0.00 | 3.33 | 5.00 | 5.00 | 0.00 | 0.67 / 1 | 3/3 |

Readings:

- **The evidence-bound dimensions agree almost exactly on current prompts.** Consensus mean |Δ| is 0.00–0.22 on the v9/v10 rounds (the candidate applies the worst-window record rule the way production does) and identity is 0.00–0.19 — both models map the identity evidence states identically.
- **Diversity is the genuine behavioral difference** (7.4–9.3 on v8+ testnet rounds), consistent with it being the documented noisiest surface of the incumbent as well.
- **Old prompt eras diverge much more** (selection max deltas 15–27 on v5/v6 rounds, where selection consumed the model's holistic overall score — the exact inconsistency class that motivated the deterministic formula). The candidate tracks the current prompt generation far better than the retired ones, which is the direction that matters.
- **Selection: 8 of 10 rounds reproduce the published UNL seat-for-seat.** The two exceptions each differ by a single churn-boundary seat: in round 15 a challenger at candidate-86 fails to displace an incumbent at 82 under the round's frozen +5 gap where production's scores let it in; in round 17 production scored a challenger 95 (≥ weakest 88 + 5, seated) where the candidate's 92 keeps the incumbent — 2–4-point score differences at exactly the boundary the v9 revision documented as roll-sensitive. Both outcomes are evidence-fair; neither is an anomaly.
- **Churn-gap fit.** The candidate's finals on round 18 occupy the same compressed band (92–97 for the top cohort) with the same 5-point-band sub-score structure, so the gap-3 calibration ("one band step moves a final by at most 1 point; noise cannot produce a 3-point margin") carries over unchanged.
- **Evidence-twin consistency (round 18, exact-evidence groups): baseline 0 violations in 4 groups, candidate 1** — two byte-identical-evidence validators received consensus 100 vs 99. One point on one pair, but it is a class of error the incumbent does not make on this round.

## Qualitative evidence review (metric 7)

Six highest-disagreement round-18 cases were read against their frozen evidence (extraction in the replay harness; sub-scores quoted as c/r/s/d/i):

1. **Unresolved-endpoint validator** (verified domain, Canada, null ASN, 30d 99.685%): production d=30 with the reasoning "missing endpoint data prevents diversity credit"; candidate d=65, crediting the country while noting the unresolved ASN. Production's hard line — no provider data, no diversity credit — is the security-minded reading; an unresolved endpoint could sit in the largest bloc. **Production better.**
2. **Outdated-software validators** (two cases, server 1.0.0 vs current 1.0.4): production s=80, candidate s=60, applied uniformly to every outdated validator. Both are defensible bands; the candidate is harsher but consistent, and at 10% weight the difference is two final points. **Neutral.**
3. **Perfect-record reliability miss**: a validator with 3 missed ledgers in 853,626 (30d 1.0) gets production r=100; the candidate gives r=95 while its own reasoning opens "Perfect agreement across all windows, but…" — the number contradicts its own text, and under the v9 rubric a perfect record earns the top band. **Production better.**
4. **Unique-provider, common-country validator** (Cable One US, 30d 77.75%): both models cap consensus at the record (77 — the record rule holds identically). Production d=95, candidate d=65. The candidate's placement is closer to a counts-based read (unique family, common country) — but its reasoning sentence couples diversity to "operational risk is high", which under v9's isolation rule (counts only; agreement evidence must not move diversity) is a rubric leak. **Split: candidate's number, production's discipline.**
5. **Hetzner-Singapore bloc member**: production d=40 (bloc membership dominant), candidate d=65 (country rarity credited). The megabloc read is the safer one for concentration risk. **Production slightly better.**
6. **Unique-country validator** (Vultr, South Africa, 30d 99.862%): production d=95; candidate d=75 while calling the location "excellent geographic diversity" — again prose above its own number. Counts-based, a unique country belongs in the top band. **Production better.**

Overall qualitative verdict: the candidate is a competent in-family scorer — it applies the consensus record rule and identity mapping exactly, its bands are internally consistent, and its reasoning is clear. But on the surfaces where the models disagree, production's judgment adheres to the current rubric more faithfully: conservative on unknown infrastructure, top-band for perfect records, diversity isolated from operational evidence, and prose that matches its numbers. Nothing in the review found a case where the candidate corrects a production error; the disagreements are either style-equivalent or production-favored. The formula's low weights absorb most of the difference — which is why selection outcomes still match — but as a judgment instrument the incumbent is not improved upon by this candidate.

## Sidecar compatibility note

The candidate requires no validator-sidecar change. The proof: round 324's real execution manifest was transformed to the candidate profile — `model.repo_id`/`served_name`/`revision`, `request.model`, `runtime.image`, and the model-path/served-name launch arguments changed; every `code.*` content hash untouched since the parser, score formula, and selector sources do not change — and the sidecar's own vendored compatibility checker (`validator_scoring_sidecar.manifest.check_compatibility`) accepts it: `passed=True, effective_mode=modal`. An instructive detail: a first transform that updated `model.*` but not `request.model` was **rejected** by the checker (`MANIFEST_INCOMPATIBLE, field=request.model`), demonstrating the gate actually guards the contract. In a real rollout the scoring service derives both fields from the same setting, so the manifest is coherent by construction; Modal-mode sidecars redeploy from it automatically at their next round, and local-mode operators restart their SGLang server against the new manifest manually. One adoption-time detail: the manifest's `launch_args` would then carry `--disable-radix-cache`, which requires adding the flag to the scoring service's manifest builder alongside the deployment — both sides of the comparison carry it, so the sidecar contract is unaffected.

## Cost and latency (excluded from the verdict)

Cold start (container boot + weights + first fresh-prefill request, no DeepGEMM precompile): 421–554 s for a 55-validator round. Warm full-round request: ~117 s cache-on, ~131 s cache-off (55 validators); ~15 s for the 3-validator devnet shape. The full evaluation — 28 inference calls across gates, characterization probes, and the 10-round sweep, plus idle scaledown windows across several boot cycles — consumed roughly 1.5–2 H100-hours on the `agti` workspace. After the runs the Modal app was stopped; the weights volume (`scoring-model-weights-qwen38`) is retained so a re-evaluation skips the download. For production planning: without a working precompile, each round would pay the JIT cost inside its first request; restoring the precompile is the identified fix.

## Conclusion

**Do not adopt at this time.**

- The decisive reason is the quality comparison: no gain. Selection outcomes are identical or boundary-noise across ten real rounds, and the qualitative review favors the incumbent's rubric adherence on every decisive case (unknown-infrastructure conservatism, perfect-record reliability, diversity isolation, one identical-evidence inconsistency the incumbent doesn't make).
- The determinism finding is a secondary cost, not the disqualifier: on the remediated profile the candidate is bit-exact, the flag would travel in every round's manifest, and sidecar reproduction would hold — were the candidate clearly better, this alone would not block adoption. What it signals is that deterministic-inference coverage for this architecture is young (the cache path is the gap this evaluation found), and adoption would take on a permanently wider reproducibility surface — cache-disabled serving mirrored into the manifest builder, a newer runtime image, no working kernel precompile — with nothing gained in return.
- The candidate is not defective — every hard gate can be satisfied on the remediated profile and its scoring is in-family — so if it is reconsidered, this record and the remediated profile are the starting point. The natural venue is the standing governance process once round orchestration is live: the model meets the pool rules (vendor FP8, single-GPU, same-family successor), and a governance round would grade it under the exam-and-judge machinery rather than by side-by-side reading.

The evaluation deliberately leaves production untouched: the incumbent (`Qwen3.6-27B-FP8`, April image, precompiled, cache-on) remains the scoring model on both environments.
