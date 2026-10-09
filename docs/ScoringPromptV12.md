# Scoring Prompt v12 — Advisory Diversity

`prompts/scoring_v12.txt` replaces `scoring_v11.txt` as the active scoring prompt, shipping together with diversity formula v1 (`docs/DeterministicDiversity.md`): the network now computes the authoritative diversity sub-score in code from the concentration counts, and the model's diversity value becomes advisory, the way its overall score became advisory under v8. `PROMPT_VERSION` moves to `v12`. The model's output shape is unchanged, so the parser, the score formula, the selector, and deployed sidecars are untouched; `scoring_v11.txt` is retained on disk for audit.

## Motivation

The model does not keep the two closed-form diversity rules the prompt states (identical counts, identical score; strictly less crowded, strictly higher). Testnet round 26 broke both, as did rounds 23 to 25 (postfiatorg/dynamic-unl-scoring#65). The fix is to compute the number in code; the prompt change only tells the model so and keeps its text from contradicting the computed number.

## The v12 changes

1. **Advisory framing.** The paragraph that already makes the overall score advisory now says the same of the diversity sub-score: the network computes the authoritative value from the concentration counts with a published formula and replaces the model's before the final score; the other four sub-scores carry the model's entire effective judgment.
2. **Dimension note.** The diversity dimension gains one sentence: the sub-score is advisory, it is still scored by the same rules so the advisory value stays comparable across rounds, and the reasoning string must not mention diversity, country, provider, concentration, or geography.
3. **Reasoning rule.** The reasoning instruction drops country, provider family, and concentration counts from the evidence to cite and states the same prohibition.
4. **Examples.** The two example reasoning strings in the output format no longer cite countries, providers, or diversity, so the examples obey the rule they sit next to.

The output format's field list is untouched. A first candidate also annotated the `diversity` field line as advisory, and that one edit broke the model's output on the live testnet set (below).

Nothing else moves: the dimension's scoring rules, the penalty policies, the network report, and the output format are byte-identical to v11.

## Validation

`scripts/replay_prompt_variants.py` gains a `v12` variant, rendered exactly like v11 (hidden `unl`, flag injection, verdict computation). Testnet round 26 (frozen under v11, 51 validators) was replayed against the pinned production runtime with the frozen request's own sampling parameters, using the published production response as the baseline.

- **The judged dimensions barely move.** Consensus and software are identical to production for all 51 validators; reliability moved on 4 (one by two bands, three by one, all down) and identity on 2 (one band down), the usual roll sensitivity.
- **Parses clean.** 51 of 51 under the production parser, no errors; a repeat returned byte-identical content (sha256 `239afa2b…`). The same text is complete on the live testnet set of 52 validators (dry run request replayed offline, byte-identical on a repeat).
- **Selection.** Running the full v12 pipeline on the replay output — the model's v12 sub-scores, diversity formula v1 over the round's frozen counts, score formula v1, the selector with the round's context — gives the published round 26 UNL exactly, 25 of 25.
- **The model keeps talking about location.** The prohibition is only partly followed: 29 of 51 reasoning strings still mention the country, the provider, or diversity (51 of 51 in production; 40 and 37 of 51 in the two earlier iterations below). The sentences point the same way as the formula, because the model reads the same counts (hosting in South Korea "provide[s] good operational and diversity signals"), so the text does not contradict the computed number in direction, only in the absence of a number. The explorer shows the computed value and explains the formula next to the text.

## Iteration findings

**The output format is not the place for prose.** The candidate that annotated the `diversity` field line with "(advisory; the network computes the authoritative value)" was clean on devnet (3 validators) and on round 26 (51 validators), then failed two testnet dry runs on the live 52-validator set the same way each time: the model keyed validator `v036`'s entry as a single space, so the production parser failed closed. The offline replay of the dry run's frozen request reproduced it byte for byte; removing that one annotation produced a complete answer on the same request, byte-identical on a repeat, and left round 26 unchanged. This is the same deterministic, data-positional corrupted-key mode the v10 revision hit, and the same lesson: edits inside the output-format section move the model's keys, so new wording goes into the instructions, never next to the field list. Testnet dry runs on the live set are therefore part of every prompt revision's validation from now on.

Three iterations of the location prohibition were tried: a soft instruction ("keep it out of the reasoning string", 40 of 51 mentions), a flat prohibition (37 of 51), and the committed one, the flat prohibition plus example reasoning strings that obey it (30 of 51). None makes the model stop citing location, which is consistent with everything else this program has learned about prose rules: the model follows them most of the time, not always. If the leftover sentences prove confusing on the explorer, the follow-up is structural rather than textual — stop rendering the concentration block and the location fields to the model at all, so it cannot cite what it does not see, and fix its advisory diversity at a constant. That changes the request shape (safe for sidecars, which replay the frozen request) and needs its own replay to confirm the other four dimensions hold without the context.

Raw output: `docs/promptv12-replays/r26_v12.json`.

## Rollout

Ships with diversity formula v1: `main`, then `devnet` with a manually triggered round, then `testnet` on its standing schedule. `scoring-model-governance` needs its v12 rules row before v12 rounds enter a governance exam; diversity leaves that row's equality, ordering, and banding checks, since the network discards the model's diversity and a defect in a discarded value has no production effect.
