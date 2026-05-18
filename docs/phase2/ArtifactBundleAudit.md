# Phase 2 Artifact Bundle Audit

This document explains why the scoring artifact bundle needs to change before
Phase 2 validator verification starts. The goal is to make every future scoring
round easy for a validator sidecar to download, understand, rerun, and compare
without relying on undocumented service behavior.

Phase 1 artifacts are good enough for public audit. Phase 2 needs more: the
artifacts must become a reproducible execution package.

## Why This Exists

Today a completed round publishes a flat set of JSON files to IPFS and stores
the same files in PostgreSQL for HTTPS fallback. A human can inspect the files
and understand what happened, but a validator sidecar cannot yet treat the
bundle as a strict verification contract.

The missing piece is not only `execution_manifest.json`. The whole bundle layout
should make the scoring lifecycle obvious:

```text
data collected -> data prepared -> model request -> model response
              -> parsed scores -> selected UNL -> signed VL -> public receipts
```

The current file names do not show those stages clearly enough.

## Current Situation

Current full-round artifacts are assembled in
`scoring_service/services/ipfs_publisher.py`.

Normal public rounds publish this shape:

```text
round CID/
  snapshot.json
  scoring_config.json
  prompt.json
  validator_id_map.json
  raw_response.json
  scores.json
  unl.json
  vl.json
  metadata.json
  raw/
    vhs_validators.json
    vhs_topology.json
    crawl_probes.json
    asn_lookups.json
    geoip_lookups.json
```

Private dry-runs store a similar shape in the private dry-run tables, but they
do not pin to IPFS and do not include `vl.json`.

Override rounds publish this smaller shape:

```text
round CID/
  unl.json
  vl.json
  metadata.json
```

That difference is intentional: override rounds skip collection, LLM scoring,
and UNL selection. They only publish an operator-supplied UNL through the VL
signing, IPFS, GitHub Pages, and on-chain memo path.

## Current Gaps

The current bundle is auditable, but not yet Phase 2-verifiable.

Key gaps:

- The layout is flat, so a verifier cannot immediately see which files are
  inputs, runtime configuration, outputs, raw evidence, or publication metadata.
- `scoring_config.json` is too small. It records model name, prompt version, and
  request settings, but not model weight hashes, Modal/SGLang image digest,
  launch arguments, CUDA/runtime versions, scoring-service git commit, parser
  version, selector version, or canonical output hashes.
- `metadata.json` hashes the files present before it is added, but the bundle
  does not have a first-class manifest that says "this is bundle layout v2 and
  these are the verification-critical files."
- The file names are short but ambiguous. `prompt.json`, `scores.json`, and
  `unl.json` make sense once you know the code, but they do not explain whether
  they are model input, raw model output, parsed output, or selector output.
- Publication receipts are split across places. The IPFS bundle has
  `metadata.json`, while the GitHub Pages commit URL and PFTL memo transaction
  live on the round row after later pipeline stages.
- There is no canonical "commit target" output for Phase 2 commit-reveal. A
  sidecar needs a clearly defined hash target, not an informal choice of
  `scores.json` or `unl.json`.

## Future Goal

After Phase 2 is complete, a validator sidecar should be able to do this:

```text
1. Fetch round bundle CID
2. Read bundle.json
3. Verify every file hash listed in bundle.json
4. Read runtime/execution_manifest.json
5. Confirm the model, runtime, prompt, parser, and selector match local setup
6. Send inputs/model_request.json to the local model
7. Compare local response with outputs/model_response.json
8. Parse local response and compare with outputs/validator_scores.json
9. Run selector and compare with outputs/selected_unl.json
10. Commit/reveal the agreed canonical output hash on-chain
```

Visually, the target flow should look like this:

```text
raw evidence
    |
    v
inputs/validator_evidence.json
    |
    v
inputs/model_request.json + runtime/execution_manifest.json
    |
    v
outputs/model_response.json
    |
    v
outputs/validator_scores.json
    |
    v
outputs/selected_unl.json
    |
    v
outputs/signed_validator_list.json
```

## File Classification

The table below classifies every current artifact by its Phase 2 role.

| Current file | What it really is | Phase 2 classification | Recommendation |
|---|---|---|---|
| `metadata.json` | Bundle metadata, file hashes, gateway URLs, DB-IP attribution, optional override flag | Legacy-only after cutover | Do not publish in new Phase 2 bundles; replace with `bundle.json` and retain only for historical Phase 1 rounds |
| `snapshot.json` | Normalized validator evidence after collection and enrichment | Required for verification | Move to `inputs/validator_evidence.json` |
| `scoring_config.json` | Lightweight model and request settings | Legacy-only after cutover | Do not publish in new Phase 2 bundles; replace with `runtime/execution_manifest.json` and retain only for historical Phase 1 rounds |
| `prompt.json` | Exact OpenAI-compatible messages sent to the model | Required for verification | Rename to `inputs/model_request.json` |
| `validator_id_map.json` | Anonymous prompt IDs mapped back to validator master/signing keys | Required for parsing and audit | Rename to `inputs/validator_map.json` |
| `raw_response.json` | Raw unparsed LLM response text | Required for deterministic comparison | Rename to `outputs/model_response.json` |
| `scores.json` | Parsed validator scores, dimension scores, reasoning, network report | Required for verification and UI | Rename to `outputs/validator_scores.json` |
| `unl.json` | Mechanical selector output: selected UNL and alternates | Required for verification | Rename to `outputs/selected_unl.json` |
| `vl.json` | Signed Validator List v2 JSON consumed by postfiatd/GitHub Pages | Required for publication verification, not for rerunning LLM | Rename inside the artifact bundle to `outputs/signed_validator_list.json`; keep the public `/vl.json` serving path unchanged unless that interface is migrated separately |
| `raw/vhs_validators.json` | Raw VHS validator API response | Audit/debug, useful for data-source verification | Keep under `raw/vhs_validators.json` |
| `raw/vhs_topology.json` | Raw VHS topology API response | Audit/debug, useful for data-source verification | Keep under `raw/vhs_topology.json` |
| `raw/crawl_probes.json` | Raw `/crawl` probe results used to map IPs to validators | Audit/debug, useful for data-source verification | Keep under `raw/crawl_probes.json` |
| `raw/asn_lookups.json` | ASN lookup results from local pyasn data | Audit/debug, useful for enrichment verification | Keep under `raw/asn_lookups.json` |
| `raw/geoip_lookups.json` | DB-IP Lite country lookup results | Audit/debug, useful for enrichment verification and attribution | Rename to `raw/geolocation_lookups.json` |

Classification meanings:

| Classification | Meaning |
|---|---|
| Required for verification | A sidecar needs this to rerun or compare the round |
| Required for publication verification | Needed to prove the published VL matches the selected output |
| Audit/debug | Useful for humans and data-source checks, but not needed for the core model rerun |
| Obsolete | Replaced by a stronger Phase 2 file |
| Legacy-only after cutover | Do not publish in new Phase 2 bundles; preserve only for reading historical rounds |

## Proposed Phase 2 Bundle Layout

Recommended new normal-round layout:

```text
round CID/
  bundle.json
  inputs/
    validator_evidence.json
    model_request.json
    validator_map.json
  runtime/
    execution_manifest.json
  outputs/
    model_response.json
    validator_scores.json
    selected_unl.json
    signed_validator_list.json
    verification_hashes.json
  raw/
    vhs_validators.json
    vhs_topology.json
    crawl_probes.json
    asn_lookups.json
    geolocation_lookups.json
```

Recommended new override-round layout:

```text
round CID/
  bundle.json
  runtime/
    execution_manifest.json
  outputs/
    selected_unl.json
    signed_validator_list.json
  raw/
```

For override rounds, `runtime/execution_manifest.json` should explicitly say:

```json
{
  "round_kind": "override",
  "inference_performed": false,
  "override_type": "custom",
  "override_reason": "Operator-supplied reason"
}
```

No `inputs/model_request.json`, `outputs/model_response.json`, or
`outputs/validator_scores.json` should exist for override rounds because no LLM
inference happened.

## Proposed Folder Changes

Introduce these folders as the stable Phase 2 contract:

| Folder | Purpose |
|---|---|
| `inputs/` | Files the scorer or verifier consumes before inference |
| `runtime/` | Model, code, environment, parser, and selector contract |
| `outputs/` | Files produced by the model, parser, selector, and VL signer |
| `raw/` | Raw source evidence kept for audit and debugging |

Use short lifecycle names instead of implementation-heavy names such as
`llm_input/`, `data_collection/`, or `data_preparation/`. The staged names are
simple, but still show where each file belongs.

Do not introduce a `receipts/` folder inside the first Phase 2 IPFS bundle yet.
The root IPFS CID, GitHub Pages commit URL, and PFTL memo transaction hash are
known only after the bundle is created. If those receipts need to become their
own immutable artifact later, publish a second post-publication receipt bundle
instead of trying to force them into the first CID.

Do not keep top-level artifact files as the primary Phase 2 contract. New
bundles should publish only the staged layout. Support for old names should
exist only where the system reads historical Phase 1 rounds.

## Proposed File Names

The goal is simple stage-based names. A developer should be able to understand
the file's role without knowing the code.

| Current name | Proposed name | Why |
|---|---|---|
| `metadata.json` | `bundle.json` | This is the entry point for the whole bundle, not just loose metadata |
| `snapshot.json` | `inputs/validator_evidence.json` | This is the normalized evidence the model request is built from |
| `prompt.json` | `inputs/model_request.json` | This is the exact request sent to the LLM |
| `validator_id_map.json` | `inputs/validator_map.json` | Shorter name, still clear |
| `scoring_config.json` | `runtime/execution_manifest.json` | The future file is a complete runtime contract, not just config |
| `raw_response.json` | `outputs/model_response.json` | This is the raw model output |
| `scores.json` | `outputs/validator_scores.json` | This is the parsed scoring result, not the raw model response |
| `unl.json` | `outputs/selected_unl.json` | This is the selector result |
| `vl.json` | `outputs/signed_validator_list.json` | This is a signed VL, not just any validator list |
| `raw/geoip_lookups.json` | `raw/geolocation_lookups.json` | Avoids implementation-specific GeoIP wording |

`verification_hashes.json` is new. It should contain the canonical hashes that
Phase 2 sidecars commit to and compare:

```json
{
  "model_response_hash": "<sha256 canonical outputs/model_response.json>",
  "validator_scores_hash": "<sha256 canonical outputs/validator_scores.json>",
  "selected_unl_hash": "<sha256 canonical outputs/selected_unl.json>",
  "signed_validator_list_hash": "<sha256 canonical outputs/signed_validator_list.json>",
  "phase2_commit_hash": "<hash target used by commit-reveal>"
}
```

Exact canonicalization rules should be defined before implementation. The safest
rule is to use one canonical JSON encoding everywhere a hash is compared by
different machines.

## Proposed `bundle.json`

`bundle.json` should be the first file a verifier reads.

Minimum recommended shape:

```json
{
  "bundle_version": 2,
  "round_kind": "normal",
  "round_number": 241,
  "network": "testnet",
  "published_at": "2026-05-18T00:00:00+00:00",
  "geolocation_attribution": "IP geolocation by DB-IP.com",
  "entrypoints": {
    "validator_evidence": "inputs/validator_evidence.json",
    "model_request": "inputs/model_request.json",
    "execution_manifest": "runtime/execution_manifest.json",
    "model_response": "outputs/model_response.json",
    "validator_scores": "outputs/validator_scores.json",
    "selected_unl": "outputs/selected_unl.json",
    "signed_validator_list": "outputs/signed_validator_list.json",
    "verification_hashes": "outputs/verification_hashes.json"
  },
  "file_hashes": {
    "inputs/validator_evidence.json": "<sha256>",
    "inputs/model_request.json": "<sha256>",
    "runtime/execution_manifest.json": "<sha256>",
    "outputs/model_response.json": "<sha256>",
    "outputs/validator_scores.json": "<sha256>",
    "outputs/selected_unl.json": "<sha256>",
    "outputs/signed_validator_list.json": "<sha256>",
    "outputs/verification_hashes.json": "<sha256>"
  }
}
```

Do not put the final root IPFS CID inside `bundle.json`; that creates a circular
reference because the CID depends on the file content. The CID should remain in
the scoring round API response and on-chain memo.

The GitHub Pages commit URL and PFTL memo transaction hash are also produced
after the IPFS bundle is created. Keep them on the round row unless the pipeline
later introduces a second post-publication receipt bundle.

## What To Add

Add these files for Phase 2-eligible rounds:

| New file | Purpose |
|---|---|
| `bundle.json` | Primary bundle index, layout version, entrypoints, hashes, attribution |
| `runtime/execution_manifest.json` | Complete model/runtime/request/code contract for rerunning the round |
| `outputs/verification_hashes.json` | Canonical hashes used by sidecars and commit-reveal |

Add these concepts to existing content:

- `bundle_version`, starting at `2`.
- `round_kind`, with values such as `normal`, `dry_run`, or `override`.
- `inference_performed`, especially important for override rounds.
- Canonical JSON hash rules for files that validators compare.
- A clear historical policy: Phase 1 bundles are audit-only unless backfilled
  with complete execution manifests.

## What To Change

Change the artifact builder to group files by lifecycle stage:

```text
inputs/   -> what the scorer receives
runtime/  -> how the scorer must run
outputs/  -> what the scorer and selector produced
raw/      -> raw source evidence used to build normalized inputs
```

Change `metadata.json` responsibility:

- Current role: general metadata plus file hashes.
- New role: historical artifact only.
- New primary file for new bundles: `bundle.json`.

Change `scoring_config.json` responsibility:

- Current role: small display/config file.
- New role: replaced by `runtime/execution_manifest.json`.

## What To Remove Or Stop Treating As Verification-Critical

Do not publish old names in new Phase 2 bundles if the cutover is coordinated.
Old names are still valid for historical Phase 1 rounds, but they should not
continue as leftovers in the new artifact contract.

Recommended clean cutover:

1. Let the next scheduled weekly testnet round publish the old layout.
2. Merge the artifact publishing changes to testnet only after that round is
   complete.
3. Before triggering the first changed scoring round, update artifact consumers
   such as Explorer, docs, tests, and internal scripts to the staged layout.
4. Publish only the staged Phase 2 names for new changed bundles.
5. Keep historical read support for old Phase 1 names indefinitely.
6. For new Phase 2-eligible bundles, treat only the new layout as the
   verification contract.

Files that should stop being Phase 2-critical:

| File | Reason |
|---|---|
| `scoring_config.json` | Too small; superseded by `runtime/execution_manifest.json` |
| `metadata.json` | Too generic; superseded by `bundle.json` as primary verifier entrypoint |
| Old top-level `prompt.json`, `scores.json`, `unl.json`, `vl.json` | Superseded by stage-based names in the new verifier contract |

## Implementation Order

Recommended order for the actual code work:

1. Add the new staged file names and remove old top-level names from new bundle
   publication.
2. Add `bundle.json` with `bundle_version = 2`, entrypoints, and file hashes.
3. Add `runtime/execution_manifest.json` with placeholder fields that are
   available today, then fill missing runtime/model hash fields in the next
   step of M2.0.
4. Add `outputs/verification_hashes.json`.
5. Mark the first round with all required manifest fields as the first
   Phase 2-eligible round.

## Compatibility Policy

Never rewrite existing Phase 1 IPFS CIDs. IPFS content is immutable, and those
rounds should remain historical audit records.

Use this policy:

| Round type | Policy |
|---|---|
| Existing Phase 1 rounds | Audit-only unless fully backfilled outside the CID |
| New Phase 2 layout test rounds | Publish only staged names |
| First complete manifest round | Mark as first Phase 2-eligible round |
| Override rounds | Publish explicit no-inference manifest and only override-relevant outputs |
| Dry-runs | Keep private; use same staged shape where practical, but do not pin to IPFS |

## Decision Summary

Recommended direction:

- Move from a flat audit folder to a staged verification bundle.
- Use `bundle.json` as the primary entrypoint.
- Use `runtime/execution_manifest.json` as the reproducibility contract.
- Use `outputs/verification_hashes.json` as the sidecar comparison target.
- Rename ambiguous files into simple stage-based names.
- Do not publish old top-level names in new bundles after a coordinated cutover.
- Treat all old Phase 1 CIDs as audit-only unless a future policy explicitly
  backfills enough information to verify them.

This gives future developers a clear reason for the artifact change: Phase 1
published evidence for humans; Phase 2 must publish an execution package for
machines.
