# Deterministic Diversity Sub-Score

Design for moving the diversity sub-score from the model's judgment to a deterministic, published function of the two concentration counts the collector already produces. The model keeps owning the other four sub-scores and the reasoning; a content-hash-pinned formula owns diversity; score formula v1 and the selector consume its output unchanged. This document is the specification the scoring service, the validator sidecar, and the explorer implement. It follows `docs/DeterministicFinalScore.md` in shape and in rollout mechanics.

## Why

Since prompt v9 the model is told to score diversity from two numbers only — how many validators in the round share the validator's country and how many share its provider family — with two closed-form rules: identical counts must give identical sub-scores, and a validator no more concentrated on either axis and strictly less on one must score strictly higher. The model does not keep those rules. Testnet round 26 (2026-10-06, prompt v11) scored two validators with identical counts (1 country, 1 provider) at 90 and 95, and one of four validators sharing a situation (1 country, Vultr 10) at 85 against 95 for the other three; rounds 23, 24 and 25 each carry two or three such splits, and the same validator in an unchanged situation moved from 85 in round 23 to 40 in round 24 (postfiatorg/dynamic-unl-scoring#65). The v9 and v10 revision records already named diversity the noisiest sub-score and computing it in code the guarantee-grade fix.

The effect on outcomes has been small — one sub-score band is half a final-score point — but the rules are published, validators read their scores on the explorer, and the inputs are two integers. Nothing in diversity needs judgment: the model was asked to do arithmetic, and the fix is to let code do it.

## Diversity formula v1

Inputs per validator, read from the frozen `inputs/diversity_inputs.json`: `country_validators` (validators sharing its country, itself included, or `null` when the country is unknown), `provider_validators` (the same for its provider family), and the round's `resolved_endpoints` (validators with a resolved provider family, the same count the concentration block reports as total minus `unresolved_endpoints`). Both counts are exactly the numbers the concentration block shows the model; `resolved_endpoints` scales both axes for every validator, including the few whose provider is unknown but whose country is counted. The file is built by `build_diversity_inputs` in `scoring_service/services/provider_families.py` from the same `compute_concentration` call that renders the NETWORK CONCENTRATION block, so the model and the formula see the same numbers.

```
others     = resolved_endpoints - 1
axis(c)    = max(0, 50 * others - 119 * (c - 1))      # known axis, scaled by others
axis(null) = 10 * others                               # unknown axis
diversity  = round_half_up((axis(country) + axis(provider)) / others)
```

All arithmetic is integer arithmetic; the division is a single half-up rounding at the end. When `others` is zero (one resolved validator, or none, for example when every ASN lookup failed but geolocation worked) each known axis is worth 50 and each unknown axis 10, uniformly within the round, so no validator is favoured.

| parameter | value | role |
|---|---|---|
| axis points | 50 | each axis is worth half of the 100 points |
| axis penalty | 119 | points an axis loses when every other resolved validator shares it; above 50, so an axis bottoms out at zero before full crowding (it rounds to zero from 19 sharers of 44 and is exactly zero from 20) |
| unknown-axis points | 10 | a fixed fraction for an axis whose value is unknown; two unknown axes give 20, the value the model gave every fully unknown validator in rounds 24–26 |

The parameters are pinned in every round's execution manifest under `code.diversity_formula.parameters` next to the module's content hash, and repeated in `outputs/final_scores.json` under `diversity_formula`.

### Properties

- Identical counts give identical sub-scores, and a validator no more concentrated on either axis and strictly less on one scores strictly higher, as long as neither axis has bottomed out and the round has fewer than 120 resolved endpoints (beyond that one extra sharer can round to the same integer). These are exactly the two rules the prompt states and the governance checker encodes.
- The two axes are independent: being unique in one still earns its half when the other is crowded, which is what the prompt asks for.
- A half-known validator (country known, provider unknown, or the reverse) is scored on the known axis and receives the fixed fraction on the other, so partial evidence is neither ignored nor punished as if absent.
- The number is relative to the round: it moves when validators join or leave, as the model's did. The explorer says so in one sentence.

### Calibration

The axis penalty is the one value with no natural answer. It was set by a rule rather than by taste: over testnet rounds 23–26 the formula's mean diversity equals the model's mean (48.5), so switching the owner of the number does not shift the balance between the five dimensions in score formula v1. 119 is the integer that satisfies that rule. Worked examples for round 26 (44 resolved endpoints):

| situation | model gave | formula |
|---|---|---|
| unique provider, unique country | 90 / 95 | 100 |
| Vultr (10), unique country | 95 / 85 | 75 |
| Akamai (1), Japan (2) | 95 | 97 |
| Hetzner (14), Germany (9) | 30 | 42 |
| Hetzner (14), United States (15) | ~30 | 25 |
| Canada (3), provider unknown | 60 (20 in round 24) | 54 |
| location unknown | 20 | 20 |

### Validation

Replaying rounds 25 and 26 with the formula replacing the model's diversity and everything else unchanged (the published model output for the other four sub-scores, score formula v1, the selector with each round's frozen context and previous UNL):

- Round 26: the selected UNL is identical to the published one, 25 of 25.
- Round 25: 24 of 25. The one swap is between two validators the model had scored identically (both final 90, both diversity 40), one on Vultr in the United States and one on Hetzner in Germany; the formula resolves the tie by crowding, as the rules say it should.
- Zero equality and ordering violations in both rounds, by construction.

The same replay with the uncalibrated sketch (50 points per axis) moved one seat per round the other way, lifting Hetzner/Germany validators by 36 points; the calibration rule exists to prevent exactly that kind of silent rebalancing.

## What changes

- **Pinned module** `scoring_service/services/diversity_formula.py`: `compute_diversity`, `apply_diversity_formula` (returns a copy of the parsed result with diversity replaced, fails closed on a validator without inputs), and the published parameters. Pinned in the manifest as `code.diversity_formula` with `module`, `content_sha256`, `version`, `parameters`, and `inputs` (the frozen file path).
- **Frozen input** `inputs/diversity_inputs.json`, written at input-freeze time for normal rounds and into the review files for dry runs, sorted by master key, hash-covered by `bundle.json` like every other input. The sidecar reads it; nothing recomputes counts after the freeze.
- **Pipeline**: `select_unl(apply_formula(apply_diversity_formula(parsed, inputs)), previous_unl)` in the orchestrator, for rounds and dry runs alike.
- **Artifacts**: `outputs/validator_scores.json` stays byte-stable as pure model output (its hash backs the PARSED verification level). `outputs/final_scores.json` gains `diversity_formula` and, per entry, `model_diversity` and `diversity`; its `final_score` is computed from the computed diversity.
- **Prompt v12** (`docs/ScoringPromptV12.md`): the model is told its diversity sub-score is advisory and computed by the network, still scores it by the same rules so the advisory value stays comparable, and keeps diversity out of the reasoning string so the text on the explorer cannot contradict the number next to it. The model's output shape does not change.
- **Explorer**: displays `diversity` from `final_scores.json` when present, the model's value for older rounds, and explains the formula in the methodology text.
- **Governance**: prompt v12 needs its rules row. Diversity leaves the row's equality, ordering, and banding checks, because the network discards the model's diversity under v12 and a defect in a discarded value has no production effect.

## Rollout and sidecar compatibility

The model's output shape is unchanged and the manifest section is additive, so deployed sidecars keep participating: their manifest gates ignore unknown `code.*` sections, they reproduce the model step in full, and they match the foundation at the RAW and PARSED levels, the two the convergence acceptance rule uses. Their recomputed selection differs from the foundation's, which the convergence report records at the diagnostic SELECTED_UNL level and the explorer deliberately does not surface. A sidecar that vendors `diversity_formula.py` reproduces the full chain, including the computed diversity and the selection. The sidecar update is therefore a leisure upgrade, announced with the rollout, not a prerequisite — the same model as the July score-formula rollout.

Order: this revision lands on `main`, then `devnet` with a manually triggered round, then `testnet` on its standing schedule. Deploy only while no round is between input freeze and publication (`AWAITING_COMMIT_CLOSE`, a three-hour window on testnet): a package frozen before the deploy carries no `diversity_inputs.json`, and publishing it under the formula is refused, which fails that round at publication and releases its VL sequence; the sidecar image, the explorer, and the governance row ship alongside; `scoring-model-governance` merges its v12 row once `prompts/scoring_v12.txt` is on the matching branch here.
