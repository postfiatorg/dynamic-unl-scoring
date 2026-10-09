# Scoring Prompt v12 — Advisory Diversity

`prompts/scoring_v12.txt` replaces `scoring_v11.txt` as the active scoring prompt, shipping together with diversity formula v1 (`docs/DeterministicDiversity.md`): the network now computes the authoritative diversity sub-score in code from the concentration counts, and the model's diversity value becomes advisory, the way its overall score became advisory under v8. `PROMPT_VERSION` moves to `v12`. The model's output shape is unchanged, so the parser, the score formula, the selector, and deployed sidecars are untouched; `scoring_v11.txt` is retained on disk for audit.

## Motivation

The model does not keep the two closed-form diversity rules the prompt states (identical counts, identical score; strictly less crowded, strictly higher). Testnet round 26 broke both, as did rounds 23 to 25 (postfiatorg/dynamic-unl-scoring#65). The fix is to compute the number in code; the prompt change only tells the model so and keeps its text from contradicting the computed number.

## The v12 changes

1. **Advisory framing.** The paragraph that already makes the overall score advisory now says the same of the diversity sub-score: the network computes the authoritative value from the concentration counts with a published formula and replaces the model's before the final score; the other four sub-scores carry the model's entire effective judgment.
2. **Dimension note.** The diversity dimension gains one sentence: the sub-score is advisory, it is still scored by the same rules so the advisory value stays comparable across rounds, and the reasoning string must not mention diversity, country, provider, concentration, or geography.
3. **Reasoning rule.** The reasoning instruction drops country, provider family, and concentration counts from the evidence to cite and states the same prohibition.
4. **Output field.** The `diversity` field description says "advisory; the network computes the authoritative value".
5. **Examples.** The two example reasoning strings in the output format no longer cite countries, providers, or diversity, so the examples obey the rule they sit next to.

Nothing else moves: the dimension's scoring rules, the penalty policies, the network report, and the output format are byte-identical to v11.

## Validation

`scripts/replay_prompt_variants.py` gains a `v12` variant, rendered exactly like v11 (hidden `unl`, flag injection, verdict computation). Testnet round 26 (frozen under v11, 51 validators) was replayed against the pinned production runtime with the frozen request's own sampling parameters, using the published production response as the baseline.

- **The judged dimensions barely move.** Consensus and software are identical to production for all 51 validators; reliability moved on 4 (one by two bands, three by one, all down) and identity on 2 (one band down), the usual roll sensitivity.
- **Parses clean.** 51 of 51 under the production parser, no errors; a repeat returned byte-identical content (sha256 `8afdb681…`).
- **Selection.** Running the full v12 pipeline on the replay output — the model's v12 sub-scores, diversity formula v1 over the round's frozen counts, score formula v1, the selector with the round's context — gives the published round 26 UNL exactly, 25 of 25.
- **The model keeps talking about location.** The prohibition is only partly followed: 30 of 51 reasoning strings still mention the country, the provider, or diversity (51 of 51 in production; 40 and 37 of 51 in the two earlier iterations below). The sentences point the same way as the formula, because the model reads the same counts (Vultr in South Korea "adds geographic diversity, though the provider is common"), so the text does not contradict the computed number in direction, only in the absence of a number. The explorer shows the computed value and explains the formula next to the text.

## Iteration findings

Three iterations were tried: a soft instruction ("keep it out of the reasoning string", 40 of 51 mentions), a flat prohibition (37 of 51), and the committed one, the flat prohibition plus example reasoning strings that obey it (30 of 51). None makes the model stop citing location, which is consistent with everything else this program has learned about prose rules: the model follows them most of the time, not always. If the leftover sentences prove confusing on the explorer, the follow-up is structural rather than textual — stop rendering the concentration block and the location fields to the model at all, so it cannot cite what it does not see, and fix its advisory diversity at a constant. That changes the request shape (safe for sidecars, which replay the frozen request) and needs its own replay to confirm the other four dimensions hold without the context.

Raw output: `docs/promptv12-replays/r26_v12.json`.

## Rollout

Ships with diversity formula v1: `main`, then `devnet` with a manually triggered round, then `testnet` on its standing schedule. `scoring-model-governance` needs its v12 rules row before v12 rounds enter a governance exam; diversity leaves that row's equality, ordering, and banding checks, since the network discards the model's diversity and a defect in a discarded value has no production effect.
