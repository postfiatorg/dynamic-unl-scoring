# Bundle Verification Guide

This guide explains how a validator sidecar or developer verifies one newly staged Dynamic UNL scoring bundle.

The goal is straightforward:

```text
Can I prove this published bundle is intact, understand how it was produced,
and compare its important outputs with the results I calculate locally?
```

This document does not define a new schema and does not change scoring behavior. It is the step-by-step procedure for using the files that are already published in the staged bundle.

## The Mental Model

Think of the bundle as three layers:

```text
bundle.json
  "Here are the files, and here is the hash of each file."

runtime/execution_manifest.json
  "Here is the model, runtime, request, and code contract for this round."

outputs/verification_hashes.json
  "Here are the output hashes a verifier should compare."
```

The verifier flow is:

```text
fetch bundle
  -> check bundle.json
  -> verify every listed file hash
  -> read execution_manifest.json
  -> rerun or inspect the round
  -> compare local output hashes with verification_hashes.json
  -> classify the result
```

## Eligibility

A round is verifier-ready only when its bundle contains the staged verification files:

```text
bundle.json
runtime/execution_manifest.json
outputs/verification_hashes.json
```

Verifier-ready eligibility starts with the first public scoring round published after deployment of commit `de74a0bf616c882a8d1f7dea23a4fede6f4ea2b4` or a later descendant.

Older flat bundles are still valid historical audit records, but they are not verifier-ready packages. If a bundle only has files such as `metadata.json`, `snapshot.json`, `scores.json`, `unl.json`, or `vl.json`, classify it as `Not eligible` for this procedure.

## Files By Round Kind

Normal scoring rounds should have:

```text
bundle.json
inputs/validator_evidence.json
inputs/model_request.json
inputs/validator_map.json
runtime/execution_manifest.json
outputs/model_response.json
outputs/validator_scores.json
outputs/selected_unl.json
outputs/signed_validator_list.json
outputs/verification_hashes.json
raw/...
```

Private dry-runs should have the same shape, except they do not produce:

```text
outputs/signed_validator_list.json
```

No-inference override rounds should have:

```text
bundle.json
runtime/execution_manifest.json
outputs/selected_unl.json
outputs/signed_validator_list.json
outputs/verification_hashes.json
```

Override rounds do not have model input, model response, or parsed model scores.

## Step 1: Fetch `bundle.json`

Start with `bundle.json` from either IPFS or the scoring service HTTPS fallback. The source does not matter; the file content must verify the same way.

Check:

```text
bundle_version = 2
round_kind = normal | dry_run | override
entrypoints includes the files needed for that round kind
file_hashes includes outputs/verification_hashes.json
file_hashes does not include bundle.json
```

`bundle.json` must not hash itself. That would create a circular dependency.

## Step 2: Verify The Bundle Files

For every file listed in `bundle.json.file_hashes`:

```text
1. Fetch the file.
2. Canonicalize the JSON.
3. Hash it.
4. Compare the hash with the value in bundle.json.file_hashes.
```

Use this canonical hash rule:

```text
json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
encode as UTF-8
sha256(bytes).hexdigest()
```

This ignores formatting differences like indentation and key order. It does not ignore real JSON content differences.

If any listed file hash does not match, stop and classify the bundle as `Mismatch`.

## Step 3: Read `runtime/execution_manifest.json`

The execution manifest tells the verifier what kind of execution to expect.

For a normal round:

```text
round.kind = "normal"
round.inference_performed = true
```

For a private dry-run:

```text
round.kind = "dry_run"
round.inference_performed = true
```

For an override round:

```text
round.kind = "override"
round.inference_performed = false
```

For normal rounds and dry-runs, use the manifest to understand the expected model repository, model revision, runtime image, launch arguments, request settings, prompt, parser, selector, VL generator, and code commit.

For override rounds, do not expect model execution. The manifest should include an `override` object explaining the override type and reason.

## Step 4: Compare Output Hashes

Read `outputs/verification_hashes.json`. This is the main comparison target for verifier results.

For a normal round, compare these hashes:

```text
outputs/model_response.json          -> model_response_hash
outputs/validator_scores.json        -> validator_scores_hash
outputs/selected_unl.json            -> selected_unl_hash
outputs/signed_validator_list.json   -> signed_validator_list_hash
```

For a private dry-run, compare these hashes:

```text
outputs/model_response.json          -> model_response_hash
outputs/validator_scores.json        -> validator_scores_hash
outputs/selected_unl.json            -> selected_unl_hash
```

For an override round, compare these hashes:

```text
outputs/selected_unl.json            -> selected_unl_hash
outputs/signed_validator_list.json   -> signed_validator_list_hash
```

If the verifier reruns the round locally, it should produce local output files, hash them with the same canonical rule, and compare those hashes with `outputs/verification_hashes.json`.

## Step 5: Classify The Result

Use one of these outcomes:

| Outcome | Use when |
|---|---|
| `Verified` | Required staged files exist, all `bundle.json.file_hashes` match, manifest semantics match the round kind, and verifier output hashes match |
| `Mismatch` | A required file exists but its bundle hash or verifier output hash does not match |
| `Not eligible` | The round uses the older flat artifact shape or predates the verifier-ready cutover |
| `Incomplete` | The round looks staged, but a required file for its round kind is missing |

Do not rewrite old artifacts to make them eligible. Eligibility comes from the bundle shape that was actually published.

## Important Boundaries

The public `/vl.json` path is still the operational Validator List distribution path. Inside the verification bundle, the same signed Validator List is represented as `outputs/signed_validator_list.json`.

GitHub Pages commit URLs, on-chain memo transaction hashes, and final root IPFS CIDs are publication receipts. They can prove where a bundle was published, but they are not part of the canonical output hashes.
