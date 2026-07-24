# Deterministic Final Score

Design for moving the authoritative per-validator final score from the model's holistic judgment to a deterministic, published function of the five dimensional sub-scores. The model keeps owning the sub-scores; a content-hash-pinned formula owns the final score; the mechanical selector consumes formula output. This document is the specification the scoring service, the validator sidecar, and the explorer implement.

## Motivation

Testnet rounds 12–15 established a real inconsistency class in the model's overall scores: identical sub-score vectors diverging by up to 10 points, dominance violations, and the round 15 rank-1 artifact where a validator outscored its evidence-twin by 4 points on the domain string alone. Two controlled prompt-v7 replays on the round's pinned runtime (recorded in `ScoringPromptV7.md`) proved the boundary of prompt engineering: local, per-validator-checkable rules land reliably, but the model cannot enforce a global cross-validator constraint on the overall score in a single pass — the noise relocates instead of disappearing.

The dimensional sub-scores were the consistent part of the output throughout. The fix is therefore architectural, and it extends a boundary the pipeline already has: the model judges, code composes. Selection, churn control, VL generation, and publication were always deterministic; this design moves the final score across that line too.

## Score formula v1

All inputs are the parser-validated integer sub-scores (0–100): `consensus` (c), `reliability` (r), `software` (s), `diversity` (d), `identity` (i). All arithmetic is integer arithmetic; no floating point exists anywhere in the computation.

```text
weighted_sum = (50*c + 20*r + 10*s + 10*d + 10*i) // 100      # floor division
final_score  = min(weighted_sum, c + 25)
```

Parameters:

| Parameter | Value | Role |
|---|---|---|
| weights | consensus 50, reliability 20, software 10, diversity 10, identity 10 (sum 100) | relative dimension influence, mirroring the prompt's declared importance ordering |
| consensus gate margin | 25 | caps the final score at `consensus + 25`: a validator not participating in consensus cannot score well on secondary virtues |

The result is always in 0–100 (`weighted_sum` is at most 100 and the `min` can only lower it). The formula lives in its own module in the scoring service (planned: `scoring_service/services/score_formula.py`), and — like the parser and selector — its source content hash and parameters are pinned in every round's execution manifest, so each round proves exactly which formula produced its scores.

### Properties (the v7 rules, by construction)

- **Deterministic and reproducible**: integer arithmetic on integers; any reimplementation from this spec is bit-identical.
- **Identical sub-scores ⇒ identical final score**: trivially.
- **Dominance-consistent**: both terms of the `min` are monotone non-decreasing in every sub-score, so a validator whose sub-scores are all ≥ another's can never receive a lower final score.

These are exactly the constraints v7 demanded from the model and the model could not hold.

### Why the consensus gate exists

A least-squares fit of the model's published overall scores across rounds 12–15 (n = 182: 45 + 45 + 42 + 50) against the sub-scores shows the model's behavior is not linear: the fit degenerates (near-zero or negative weights on three dimensions) and misses the degraded tail by up to 28 points, because the model treats catastrophic consensus multiplicatively — an offline validator with strong secondary evidence gets ~15–25 overall, where a pure weighted sum yields 39–43 for the observed offline validators: 43 under their published sub-score vectors, above the eligibility cutoff of 40, and 39 under v8 semantics (consensus 0), below it by a single point. A linear-only formula would leave offline validators selectable or hovering at the cutoff. The gate reproduces the model's (correct) severity behavior deterministically: with prompt v7/v8 semantics an offline validator's consensus sub-score is 0, capping its final score at 25.

### Worked examples

| c | r | s | d | i | weighted_sum | final | Note |
|---|---|---|---|---|---|---|---|
| 100 | 90 | 100 | 40 | 80 | 9000 // 100 = 90 | min(90, 125) = **90** | round 15 rank-1 cohort shape |
| 100 | 85 | 100 | 50 | 80 | 9000 // 100 = 90 | **90** | the round 15 "92 vs 88" twin group — all members now identical |
| 99 | 91 | 100 | 55 | 75 | 9070 // 100 = 90 | min(90, 124) = **90** | floor division discards the sub-integer remainder |
| 96 | 70 | 100 | 62 | 50 | 8320 // 100 = 83 | min(83, 121) = **83** | mid-table validator |
| 0 | 85 | 100 | 40 | 80 | 3900 // 100 = 39 | min(39, 25) = **25** | offline validator: gate binds, ineligible with margin |

### Empirical validation

Evaluated against the published artifacts of rounds 12–15 and the v7 replay of round 15 (the forward-looking regime — offline consensus already scored 0 there). The analysis is recomputable from public data: each round's frozen input package, its `outputs/validator_scores.json`, and the v7 replay record in `ScoringPromptV7.md`.

- **No eligibility change on any historical round**: zero validators cross the score-40 cutoff line in either direction across all four rounds.
- **Robust to the parameter choice**: five weight perturbations (consensus 40–60, others shifted accordingly) produce zero cutoff flips and the identical round 15 top-20 — the weights shape leaderboard spacing, not membership. Gate margins up to 25 are safe: the gate binds at `consensus + margin`, and the observed degraded validators (consensus 10 in the published rounds, weighted sums up to 43) first reach the 40 cutoff exactly at margin 30 — which is why 25 is the ceiling.
- **Forward simulation**: applying the formula to the v7-replay sub-scores and running the real selection (cutoff 40, max 20, min gap 5, churn against round 14's UNL) yields a 20-seat UNL with 19/20 overlap with the published round — the single difference being legitimate churn-control movement, not the anomaly class. The twin group that published as 92/88 lands uniformly on 90; the three offline validators land on 25.

## Prompt v8

v8 changes the template, not the contract:

- The response schema is **unchanged** — every validator entry still carries `score`, the five sub-scores, and `reasoning`. The deployed sidecars' vendored parser requires the `score` field; removing it would break their LLM-level verification, which is the one thing that must keep working.
- The cross-validator consistency machinery that v7 added and the replays disproved (the two-step protocol, uniform weighting, dominance self-checks) is **removed** — the formula satisfies those properties by construction, so the model stops straining at instructions it cannot follow.
- The framing becomes honest: `score` is described as the model's advisory holistic judgment, and the template states that the network computes the authoritative final score from the sub-scores with a published formula. The advisory score is still published in the round artifacts — a permanent measurement of how far the model's holistic judgment drifts from the formula — but deliberately not displayed in the explorer UI, to avoid presenting two competing numbers.

Sidecars replay rounds from the frozen `inputs/model_request.json`, so template text changes are transparent to them; only response-schema changes would not be, and there are none.

## Artifact and manifest changes

All changes are additive; nothing existing moves or changes shape.

- **`outputs/validator_scores.json` stays byte-stable as pure model output.** Its canonical hash backs the PARSED verification level; the formula must not touch it.
- **New `outputs/final_scores.json`** in the final audit bundle: a self-contained record carrying the formula version, weights, gate margin, and per-validator `{master_key, model_score, final_score}` entries sorted by master key, hashed under the same canonical JSON rule as every other artifact.
- **`outputs/verification_hashes.json`** gains a `final_scores_hash` key (additive).
- **Execution manifest** gains an additive `code.score_formula` section — module path, source `content_sha256`, and parameters (weights, gate margin) — mirroring the existing parser/selector conventions. `schema_version` stays 1: the deployed sidecars' manifest-compatibility gate hard-fails on unknown schema versions, and unknown *fields* are ignored, so additive is the only safe shape.
- **`ExecutionManifestSchema.md`** is updated with the new section when the implementation lands.

## Convergence acceptance change

The commit-reveal payload (three hashes: raw model response, parsed scores, selected UNL; `protocol_version` 1) is **unchanged** — deployed sidecars keep sending exactly what they send today.

What changes is what acceptance means, for every participant uniformly:

- **A reveal is valid when its signatures, windows, announcement binding, and reveal-to-commit commitment binding check out and its RAW and PARSED hashes match the foundation's.** These are the two levels only an actual model rerun on the pinned runtime can produce — the sidecar's irreplaceable job of proving the foundation did not tamper with the LLM.
- **The `selected_unl_hash` becomes diagnostic-only.** Everything after the parser is deterministic and recomputable by anyone from the published artifacts, so matching parsed scores already implies the final scores and the UNL. The third hash is kept in the payload (removing it would itself be a protocol change) and is used to localize divergence when something does go wrong: an old image's hash reflects legacy selection over model scores, a new image's reflects selection over formula scores, and either mismatch with an otherwise-valid reveal points at the deterministic tail rather than the model.

No protocol-version bump, no per-version acceptance policy, no forced sidecar upgrade. Sidecars commit before the foundation's output hashes are public (the M2.8.1 withholding boundary), so commitment behavior is unaffected. The sealed convergence report keeps its per-level tallies but states validity on the two LLM levels; the report schema adjustment and its explorer rendering land with the implementation.

## Selection hand-off

`unl_selector.select_unl` is unchanged — it consumes the final scores instead of the model scores. Cutoff (40), hard maximum size, churn-control minimum gap, previous-UNL semantics, and the deterministic `(score desc, master_key asc)` tie-break all stay as they are. The eligibility cutoff now sits on a deterministic quantity, which makes the score-gap-at-the-boundary noise class from rounds 12–15 structurally impossible.

The substitution happens in the orchestrator — it applies the formula to the parsed result and hands the selector final scores — because the selector source file itself must not change: deployed sidecars' manifest gates validate `code.parser.content_sha256` and `code.selector.content_sha256` against their vendored copies, and any edit to either file (even cosmetic) would hard-fail the gate and stop old images from participating at all.

## Compatibility invariants

The five constraints every implementation step must preserve:

1. The response schema keeps the `score` field (deployed vendored parsers require it).
2. `outputs/validator_scores.json` stays pure model output (PARSED-level hash stability).
3. The execution manifest's `schema_version` stays 1; the formula section is additive (deployed manifest gates hard-fail on unknown versions, and ignore unknown fields).
4. The commit-reveal payload format and `protocol_version` stay as they are (deployed images cannot change what they send).
5. `response_parser.py` and `unl_selector.py` stay byte-identical: deployed sidecars' manifest gates pin both files' `content_sha256` against their vendored supported sets, so any source change — even cosmetic — locks old images out of scoring entirely. The formula is a new module; the wiring lives in the orchestrator.

## Rollout

1. **Implement** in `dynamic-unl-scoring`: formula module, selection switch, artifacts, manifest section, convergence acceptance rule, prompt v8 with its revision record — validated by replaying round 15 on the pinned runtime before any deployment.
2. **Sidecar v1.2.0** (leisure upgrade, not a rollout dependency): vendors the formula module so the operator's local report verifies the full chain without a cosmetic selection mismatch. Old images remain fully valid participants indefinitely.
3. **Devnet**: v8 and the formula deploy together on the environment branch. The shadow round runs with mixed sidecar images — at least one foundation sidecar stays on the old image to prove the old path stays green under the new acceptance rule, the others run v1.2.0 to prove the full chain.
4. **Testnet** after a clean devnet round, followed by the operator notice (upgrade at leisure) and the community results update.
5. **Explorer** follow-up: leaderboard on the final score (the advisory model score stays in the artifacts, not the UI), formula explainer, convergence panel acceptance on the LLM levels with the selection comparison uniformly not surfaced, artifact browser picking up `final_scores.json`.

## Out of scope

Implementation-level detail (DB migration shape, API field names, sidecar module layout, explorer components) belongs to the implementation tasks that follow this design. Governance interaction is limited to a methodology note: exams grade the model on the sub-scores, since the model no longer owns the final number.
