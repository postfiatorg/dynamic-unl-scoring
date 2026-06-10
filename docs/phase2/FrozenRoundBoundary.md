# Frozen Input Boundary

This document defines the M2.1.1 frozen input boundary for normal Dynamic UNL
scoring rounds. It is the contract that future implementation should follow; it
does not itself change scoring behavior, Validator List signing, sidecar
behavior, or historical artifacts.

M2.0 already publishes staged input, runtime, raw, and output files inside the
completed final audit bundle. That bundle is created after scoring, selection,
and VL signing. M2.1 adds the separate pre-scoring input-only package described
here.

## Purpose

Validator shadow verification requires the foundation scorer and validator
sidecars to score the same immutable input. If each verifier reads live VHS
data, live `/crawl` data, current ASN lookups, or current geolocation state at a
different time, mismatches may reflect data drift instead of scoring divergence.

Normal public rounds therefore need a frozen input package. The foundation
service collects evidence, builds the exact model request and runtime contract,
pins that input package, and then scores from that frozen package. Future
validator sidecars score from the same package.

## Boundary

The `INPUT_FROZEN` boundary is reached after:

- validator evidence has been collected and normalized;
- raw source evidence has been archived;
- the exact model request has been built;
- the validator identity map has been built;
- the execution manifest has been built;
- the input package has been pinned and persisted.

The boundary is before Modal scoring. Foundation outputs are not part of the
input freeze.

Once the boundary is crossed, the round must not query live VHS, live crawler
state, ASN data, or geolocation data to rebuild scoring inputs. Any later
scoring, parsing, selection, or publication work for that round must consume the
frozen input package created before inference.

## Two CIDs

Normal public rounds have two immutable CIDs:

| Field | Meaning |
|---|---|
| `input_package_cid` | CID for the frozen input package. This is what validator sidecars score. |
| `final_bundle_cid` | Canonical name for the final audit bundle CID stored in the scoring service database, API, orchestrator result, and current memo payload. |

`ipfs_cid` is a legacy compatibility name for the same final audit bundle CID.
The database migration preserves existing CID values under the renamed
`final_bundle_cid` column. Historical on-chain memos may still contain
`ipfs_cid`, so off-repo memo parsers should support both names during historical
decode, while new service code and documentation should use `final_bundle_cid`.

## Input Package Layout

The input package contains only files needed to reproduce the scoring input.

```text
bundle.json
inputs/validator_evidence.json
inputs/model_request.json
inputs/validator_map.json
inputs/previous_unl.json
runtime/execution_manifest.json
raw/vhs_validators.json
raw/vhs_topology.json
raw/crawl_probes.json
raw/asn_lookups.json
raw/geolocation_lookups.json
```

`inputs/previous_unl.json` holds the previous round's UNL (the list of validator
master keys) that selection used for this round — an empty list for the first
round, never an omitted file. Freezing it makes UNL selection reproducible from
the package alone, since selection consumes this frozen value rather than a live
database read.

The input package must not contain foundation outputs:

```text
outputs/model_response.json
outputs/validator_scores.json
outputs/selected_unl.json
outputs/signed_validator_list.json
outputs/verification_hashes.json
```

Expected raw source files should be present even when a source returns no useful
records. Represent absence in the file content, such as an empty array or object,
rather than silently omitting the expected file. This keeps package shape stable
for sidecars.

## Input `bundle.json`

The input package has its own `bundle.json`. It indexes only the files in the
input package and must not hash itself.

Recommended fields:

```json
{
  "bundle_version": 2,
  "package_kind": "input",
  "round_kind": "normal",
  "network": "testnet",
  "round_number": 241,
  "input_frozen_at": "2026-05-19T00:00:00+00:00",
  "entrypoints": {
    "validator_evidence": "inputs/validator_evidence.json",
    "model_request": "inputs/model_request.json",
    "validator_map": "inputs/validator_map.json",
    "previous_unl": "inputs/previous_unl.json",
    "execution_manifest": "runtime/execution_manifest.json"
  },
  "file_hashes": {
    "inputs/validator_evidence.json": "<sha256>",
    "inputs/model_request.json": "<sha256>",
    "inputs/validator_map.json": "<sha256>",
    "inputs/previous_unl.json": "<sha256>",
    "runtime/execution_manifest.json": "<sha256>",
    "raw/vhs_validators.json": "<sha256>",
    "raw/vhs_topology.json": "<sha256>",
    "raw/crawl_probes.json": "<sha256>",
    "raw/asn_lookups.json": "<sha256>",
    "raw/geolocation_lookups.json": "<sha256>"
  }
}
```

Use the existing canonical JSON hash rule for file hashes:

```text
json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
encode as UTF-8
sha256(bytes).hexdigest()
```

An `input_package_hash` can be persisted as the canonical hash of the input
package's `bundle.json`. If implementation prefers to treat the root CID as the
only package identifier, the persisted metadata should still expose an
equivalent canonical identifier that future announcement protocols can
reference.

## Execution Manifest

The input package's `runtime/execution_manifest.json` is the normal round's
execution contract. It should be usable before outputs exist and should remain
valid after outputs are produced.

For normal rounds, the manifest should keep:

- `round.kind = "normal"`;
- `round.inference_performed = true`;
- the model, runtime, request, prompt, parser, selector, and canonicalization
  sections needed to reproduce model scoring and selection;
- the VL generator identity when the normal final bundle will include a signed
  Validator List.

The final bundle should repeat the same execution manifest content for the
shared input path. Avoid creating one manifest for the input package and a
different manifest for the final bundle unless a future schema explicitly
separates those contracts.

## Final Bundle Relationship

The final audit bundle remains self-contained. It has its own final
`bundle.json`, repeats the frozen input content files, and adds foundation
outputs:

```text
inputs/validator_evidence.json
inputs/model_request.json
inputs/validator_map.json
inputs/previous_unl.json
runtime/execution_manifest.json
raw/vhs_validators.json
raw/vhs_topology.json
raw/crawl_probes.json
raw/asn_lookups.json
raw/geolocation_lookups.json
outputs/model_response.json
outputs/validator_scores.json
outputs/selected_unl.json
outputs/signed_validator_list.json
outputs/verification_hashes.json
```

The final bundle does not reuse the input package's `bundle.json`. Its
`bundle.json` must index the final bundle and include a reference to the frozen
input package, for example:

```json
{
  "package_kind": "final",
  "input_package": {
    "cid": "<input_package_cid>",
    "bundle_hash": "<input_package_hash>",
    "frozen_at": "2026-05-19T00:00:00+00:00"
  }
}
```

For paths shared by the input and final bundles, canonical file hashes must
match. A verifier should be able to prove that the final outputs were produced
from the same frozen input package that sidecars scored.

## Persistence

The service should persist minimal input-freeze metadata on the public round:

- `input_package_cid`;
- `input_package_hash` or equivalent canonical package identifier;
- `input_frozen_at`.

The service uses `final_bundle_cid` for the final audit bundle CID in the
database and code. If an older database still has the legacy `ipfs_cid` column,
migrate those values into `final_bundle_cid`. The rename is semantic only:
existing values remain the same CIDs, but the field name now distinguishes the
final audit bundle from the input package, which is also an IPFS CID.

Downstream consumers should treat `final_bundle_cid` as the new public field in
round API responses and new PFTL memo payloads. Consumers that inspect
historical memos must continue accepting `ipfs_cid` as the old name for the
same final audit bundle CID concept.

The service also needs HTTPS fallback access to input package files. Because the
input package and final bundle both contain a `bundle.json`, implementation must
store input-package files in a separate namespace from final audit files. Use a
dedicated input-package fallback table so the existing final audit fallback path
keeps its current behavior. Do not let the input package's `bundle.json`
overwrite the final bundle's `bundle.json`, or the reverse.
Input-package fallback rows are insert-only for a round/file path; retries must
not mutate content under an already frozen round number.

## Lifecycle State

The lifecycle adds one round state:

```text
INPUT_FROZEN
```

This state means the input package is pinned, persisted, and immutable. The next
normal scoring work for the round must consume the frozen input package.

Do not add `ANNOUNCED`, `VERIFICATION_OPEN`, or `VERIFICATION_CLOSED` round
states as part of this input-freeze contract. Future announcement or
commit-reveal work may represent those concepts as timestamps or protocol
metadata if needed.

M2.1 does not require automatic same-round resume after a service restart. The
current stale-round failure behavior may remain in place. If a later
implementation deliberately adds resume from `INPUT_FROZEN`, that resume path
must continue from the frozen package and must not rebuild input data from live
sources.

## Failure Semantics

Preserve the current orchestrator behavior around stage failures:

- if collection or input-package creation fails before `INPUT_FROZEN`, mark the
  round `FAILED` with no input CID;
- if scoring, selection, VL signing, final bundle publication, distribution, or
  on-chain publication fails after `INPUT_FROZEN`, mark the round `FAILED` and
  retain the immutable input CID for audit and debugging;
- do not rebuild or mutate the input package under the same round number;
- do not introduce same-round retry after a recorded stage failure as part of
  this contract;
- if abandoned non-terminal rounds continue to be marked `FAILED` on restart,
  retain any already-persisted input package metadata for post-failure audit.

VL sequence behavior should remain unchanged. Failures before sequence
confirmation should release the reservation as they do today; failures after
public VL distribution should preserve the published VL state according to the
existing round states.

## Discovery And Announcements

This document does not define the on-chain round-announcement protocol. Here,
"announcement" means only that the service exposes enough immutable discovery
data for a later protocol:

- schema version;
- network;
- round number;
- round kind;
- `input_package_cid`;
- `final_bundle_cid` when the final bundle exists;
- input package hash or equivalent identifier;
- HTTPS fallback URL.

A later protocol owns the transport and validation rules for round
announcements, validator commits, validator reveals, timing windows, replay
prevention, and convergence reports.

## Dry-Runs And Overrides

Private dry-runs may use the same input-freeze concept internally, but they are
not public verification targets and should not be announced as normal rounds.

Override rounds do not perform model inference. They do not need a normal
scoring input package and must not be presented to sidecars as rounds requiring
LLM execution.

## Non-Goals

This boundary contract does not implement:

- scoring or prompt changes;
- Validator List signing changes;
- GitHub Pages publication changes;
- the future round-announcement PFTL memo/event schemas;
- commit-reveal timing;
- validator sidecar behavior;
- historical artifact rewrites.
