# Scoring Prompt v13 — Exclude Incomplete Agreement Measurements

The scoring service now excludes the numerical evidence in every agreement
window whose VHS `incomplete` flag is explicitly true. The rule applies equally
to the 1-hour, 24-hour, and 30-day windows, for every validator and regardless of
the measured score.

## Input contract

`PromptBuilder` replaces a flagged window in the model request with
`{"incomplete":true}`. Its `score`, `total`, and `missed` values are absent, so
neither the agreement ratio nor the ledger counts can influence scoring. Keeping
the quality marker distinguishes an excluded observation from a complete window
with missing or zero measurements.

Windows with a false or absent/null flag retain their complete serialized
evidence, including zero scores. The builder does not mutate the snapshot,
its content hash, validator identities, other profile fields, or concentration
counts. Frozen validator evidence continues to contain the original measurements
for audit.

Prompt v13 replaces v12's instruction to give partial measurements full weight.
Consensus ceilings, recency comparisons, and reliability patterns use only the
remaining windows. Exclusion itself is neither a penalty nor a bonus. When all
windows are excluded, the model must describe the evidence as unavailable,
without inventing an outage or perfect participation. The all-null penalty only
applies to remaining windows; exclusion alone does not trigger it.

The active template and standalone scoring default move to v13. Execution
manifests derive the prompt version and template hash from that active path.
The model response schema and the hash-pinned scoring modules are unchanged.

## Historical requests

The old templates remain unchanged. Historical replay explicitly passes
`exclude_incomplete_agreement=False` to preserve pre-v13 measurements. The
standalone v9-v12 layers also retain their previous behavior. This opt-out is
for historical reconstruction; the scoring service uses exclusion by default.

The existing prompt-variant replay harness still exposes its pre-v13 variants.
Use the active `PromptBuilder` for new v13 requests; replaying a previously
published round should use its frozen `model_request.json`.

## Regression coverage

`tests/test_incomplete_agreement.py` uses all 42 validators from
`data/testnet_snapshot.json`, keeping their real agreement ratios and ledger
counts. This March 2026 fixture predates per-window flags, so the tests set the
flags explicitly rather than claiming they were present in the capture.

A second fixture, `data/vhs_agreement_sample_20261029.json`, captures two public
VHS validators on 2026-10-29 with their original flags and measurements. One
30-day window is naturally incomplete; the other five windows are complete.
The regression parses this capture through the VHS client parser and verifies
exclusion and complete-window fidelity without modifying any source flags.
The capture records its public source and timestamp and omits unrelated fields.

The tests cover all 27 combinations of true, false, and null across the three
windows, mixed flags across validators, preservation of near-zero complete
scores, unchanged snapshot hashes and identities, deterministic output, and a
historical v12 replay retaining partial measurements. The regular prompt,
standalone scoring, and execution-manifest tests cover the version transition.

Run the repository's documented command from the repository root:

```bash
pytest
```

## Validation and rollout limits

These tests prove request construction and evidence preservation. They do not
prove that the LLM produces unchanged sub-scores for complete inputs or that the
selected UNL remains unchanged. Excluding a degraded partial window can change
consensus ceilings and reliability judgments by design.

Before deployment, run the pinned-runtime replay and live testnet dry-run
validation described in `docs/ScoringPromptV12.md`, including mixed and all-partial
windows. Coordinate the v13 governance rules row with the model-governance
maintainers. No model inference, governance rollout, or network deployment is
performed by the fixture tests.
