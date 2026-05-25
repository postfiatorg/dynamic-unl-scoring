# Commit-Reveal Protocol

This document defines the high-level commit-reveal contract for Dynamic UNL
validator shadow verification. It describes the message shapes and trust rules
that future sidecars and foundation convergence tooling should share. It does
not implement sidecar execution, chain watching, memo ingestion, convergence
report publication, or Validator List authority transfer.

The protocol builds on the frozen input package lifecycle. A normal public round
first reaches `INPUT_FROZEN`, which means the service has pinned and persisted
the immutable input package identified by `input_package_cid`,
`input_package_hash`, and `input_frozen_at`. Validator sidecars verify that
same package instead of reading live VHS, `/crawl`, ASN, or geolocation state.

## Goals

The protocol must answer four questions:

- which frozen input package a validator should score;
- how a validator commits to its result before revealing it;
- how the validator proves that the commit and reveal belong to its validator
  identity;
- how later tooling can compare revealed outputs with the foundation result
  without changing canonical VL publication.

Commit-reveal evidence is observational during Phase 2. The foundation scoring
service remains the authoritative VL publisher, and low participation or
divergence must not block normal VL distribution.

## Message Types

The protocol has four conceptual message types:

| Message | Purpose |
|---|---|
| Round announcement | Foundation says a normal round's input is frozen and gives validators the package and timing context to verify. |
| Validator commit | Validator publishes a hidden commitment to its future reveal data. |
| Validator reveal | Validator reveals output hashes and salt so the earlier commitment can be checked. |
| Convergence report | Foundation summarizes participation and match levels after reveals are processed. |

Only normal public scoring rounds are verification targets. Private dry-runs and
admin override rounds are not announced as rounds requiring validator model
execution.

## Transport

The canonical public transport should be PFTL memo transactions. Validator
commits and reveals are not API-only submissions in this protocol version; each
valid commit and reveal must be published on-chain as a PFTL transaction memo
containing the compact protocol payload.

A future scoring-service API may expose indexed announcement, commit, reveal,
and report data for sidecar convenience, but the API should include the
relevant chain transaction hash so a sidecar can verify the indexed data
against ledger history. The API should relay ledger-backed protocol facts, not
replace the on-chain memo record.

The transaction sender account is transport metadata. It may be useful for spam
analysis, rate limits, or operator support, but it is not the primary validator
identity proof in this protocol.

## Validator Identity

Validator authorship is proven by validator master-key signatures.

Each validator commit and reveal payload includes `validator_master_key` and a
hex `signature`. The signature is produced over the canonical payload without
the `signature` field. The scoring service verifies the signature against the
claimed `validator_master_key`.

PostFiat validator operators already have a signing path through the
`validator-keys` tool from `postfiatd`:

```bash
validator-keys sign "<canonical payload bytes or string>"
```

That tool signs arbitrary data with the validator key stored in
`validator-keys.json`. Because `validator-keys.json` contains master validator
key material, operator documentation must treat this as sensitive key handling.
A future protocol version may introduce delegated sidecar keys signed by the
validator master key, but this version uses direct validator master-key
signatures as the identity proof.

## Canonical Payloads

Protocol v1 uses the same canonical JSON convention as the current audit
hashing code. Hashes and signatures must be computed from canonical JSON bytes:

```python
canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
payload_bytes = canonical.encode("utf-8")
digest = hashlib.sha256(payload_bytes).hexdigest()
```

Hash-bearing protocol objects must be JSON objects, not loose string
concatenations. Implementations should reject missing required fields and
unknown fields in commit/reveal hash inputs until a later `protocol_version`
defines how those fields participate in canonicalization.

The `signature` field is never included in the bytes being signed. Signature
verification must rebuild the same canonical object from the received payload
after removing `signature`.

The hidden commitment hash and the validator signature are separate:

- `commitment_hash` hides the validator's output until the reveal phase.
- `signature` proves which validator authored the public commit or reveal
  payload.

Protocol v1 normalizes hash and salt material as lowercase hexadecimal strings:

- every SHA-256 hash field is exactly 64 lowercase hex characters;
- `salt` is 32 cryptographically random bytes encoded as 64 lowercase hex
  characters;
- `signature` is the hex output produced by the validator signing tool and is
  verified as signature material, not as a SHA-256 hash.

## Round Announcement

The round announcement is the foundation's public signal that a verification
round exists and that the input package is immutable. It should reference the
frozen input package, not the final audit bundle. At announcement time,
foundation outputs may not exist yet, and validators should not need
`final_bundle_cid` to start verification.

Required conceptual fields:

```json
{
  "type": "pf_dynamic_unl_round_announcement_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "round_kind": "normal",
  "input_package_cid": "Qm...",
  "input_package_hash": "<64 lowercase hex sha256>",
  "input_frozen_at": "2026-05-25T00:00:00+00:00",
  "commit_opens_at": "2026-05-25T00:00:00+00:00",
  "commit_closes_at": "2026-05-25T00:30:00+00:00",
  "reveal_opens_at": "2026-05-25T00:30:00+00:00",
  "reveal_closes_at": "2026-05-25T01:00:00+00:00"
}
```

Window durations remain configurable. The schema should describe the window
boundaries, but the actual values should come from deployed configuration and
devnet operational testing.

## Timing and Ledger Order

Commit and reveal timing is evaluated from validated ledger data. A commit or
reveal memo's effective submission time is the close time of the validated
ledger that includes the transaction. Implementations must not use validator
sidecar observation time, scoring-service ingestion time, indexer receipt time,
or local wall-clock time to decide whether a memo is inside a protocol window.

Protocol windows are half-open intervals:

```text
commit valid if commit_opens_at <= validated_ledger_close_time < commit_closes_at
reveal valid if reveal_opens_at <= validated_ledger_close_time < reveal_closes_at
```

This makes exact-boundary behavior deterministic. A commit included in a
validated ledger whose close time equals `commit_closes_at` is late. A reveal
included in a validated ledger whose close time equals `reveal_closes_at` is
late. A commit before `commit_opens_at` or reveal before `reveal_opens_at` is
early and not accepted for the round.

The announcement should define ordered windows where `commit_opens_at` is before
`commit_closes_at`, `reveal_opens_at` is before `reveal_closes_at`, and the
reveal window does not begin before the commit window closes. The durations and
any gap between windows remain deployment configuration until devnet testing
proves realistic values for model cold starts, scoring execution, and operator
infrastructure.

When multiple submissions are otherwise valid, the accepted commit or reveal is
chosen by deterministic validated ledger order: ascending ledger index, then
transaction order within that ledger. Transaction sender, API ingestion order,
and sidecar observation order do not affect the first-valid selection.

## Validator Commit

The validator commit publishes a salted commitment without exposing output
hashes. It binds the future reveal to the network, round, validator identity,
and frozen input package. The commit payload must be published as an on-chain
PFTL transaction memo; the memo carries only the compact fields below, not full
model responses or score artifacts.

Commit payload:

```json
{
  "type": "pf_dynamic_unl_validator_commit_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "validator_master_key": "nHU...",
  "input_package_hash": "<64 lowercase hex sha256>",
  "commitment_hash": "<64 lowercase hex sha256>",
  "signature": "<hex>"
}
```

The `commitment_hash` is computed from a separate, domain-separated preimage
that includes the future reveal data and salt:

```json
{
  "type": "pf_dynamic_unl_commitment_preimage_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "validator_master_key": "nHU...",
  "input_package_hash": "<64 lowercase hex sha256>",
  "output_hashes": {
    "model_response_hash": "<64 lowercase hex sha256>",
    "validator_scores_hash": "<64 lowercase hex sha256>",
    "selected_unl_hash": "<64 lowercase hex sha256>"
  },
  "salt": "<64 lowercase hex random salt>"
}
```

The exact commitment formula is:

```text
commitment_hash = sha256(canonical_json_bytes(commitment_preimage)).hexdigest()
```

The preimage is not the on-chain commit payload and does not include
`signature`, transaction sender, transaction hash, ledger index, memo wrapper
fields, or `input_package_cid`. The `type` field provides domain separation,
and `input_package_hash` binds the commitment to the exact package persisted at
`INPUT_FROZEN`. Changing the network, round number, validator master key,
protocol version, frozen package hash, output hashes, or salt must produce a
different `commitment_hash`.

The commit signature is computed over the commit payload without `signature`.
The signature does not hide the output. It only proves validator authorship of
the public commit payload.

## Validator Reveal

The validator reveal publishes the output hashes and salt needed to recompute
the earlier `commitment_hash`. The reveal payload must be published as an
on-chain PFTL transaction memo; the memo carries hashes and salt, not full
output files.

Reveal payload:

```json
{
  "type": "pf_dynamic_unl_validator_reveal_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "validator_master_key": "nHU...",
  "input_package_hash": "<64 lowercase hex sha256>",
  "output_hashes": {
    "model_response_hash": "<64 lowercase hex sha256>",
    "validator_scores_hash": "<64 lowercase hex sha256>",
    "selected_unl_hash": "<64 lowercase hex sha256>"
  },
  "salt": "<64 lowercase hex random salt>",
  "signature": "<hex>"
}
```

The reveal signature is computed over the reveal payload without `signature`.
To validate a reveal, tooling must:

1. verify the reveal signature against `validator_master_key`;
2. find the accepted commit for the same `protocol_version`, `network`,
   `round_number`, `validator_master_key`, and `input_package_hash`;
3. rebuild the exact commitment preimage from the reveal fields;
4. compute the canonical SHA-256 hash of that preimage;
5. compare it to the accepted commit's `commitment_hash`.

The reveal is valid only if the recomputed hash matches the accepted commit.
This means a reveal from another network, round, validator, protocol version,
or frozen input package cannot satisfy the accepted commitment even if the
output hashes and salt are copied.

The reveal intentionally omits `signed_validator_list_hash`. Validators do not
hold the foundation VL publisher key, so foundation-signed VL output is not an
independently reproducible validator commitment target. A later protocol may
add optional validator-owned output package publication for deeper auditability,
but `output_package_cid` is not required in this version.

## Convergence Report

The convergence report is the foundation's later summary of participation and
agreement. It can reference both the frozen input package and the final bundle
once final outputs exist.

Conceptual fields:

```json
{
  "type": "pf_dynamic_unl_convergence_report_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "input_package_cid": "Qm...",
  "input_package_hash": "<64 lowercase hex sha256>",
  "final_bundle_cid": "Qm...",
  "participants": [],
  "summary": {}
}
```

Detailed convergence report contents belong to later foundation-service
implementation. This document only reserves the message role and its binding to
the same round and frozen input package.

At a minimum, later convergence reporting should classify each expected
validator's participation without changing canonical VL publication:

| Outcome | Meaning |
|---|---|
| `missing_commit` | No valid commit was accepted for the validator before `commit_closes_at`. |
| `missing_reveal` | A valid commit was accepted, but no matching valid reveal was accepted before `reveal_closes_at`. |
| `revealed` | The first valid reveal matched the accepted commitment. |

Conflicting duplicate commits or reveals should be exposed as observable flags
on top of those outcomes, not as replacements for the accepted first-valid
submission. These participation outcomes are evidence for Phase 2 monitoring and
debugging only; they do not block, delay, or replace foundation VL publication.

## Validity Rules

Implementations should apply these rules when protocol helpers and sidecar
logic are added:

- reject payloads with an unsupported `protocol_version` or `type`;
- reject malformed hash fields that are not 64 lowercase hex SHA-256 strings;
- reject malformed salts that are not 64 lowercase hex characters;
- reject commits or reveals whose `network`, `round_number`, or
  `input_package_hash` does not match the announced round;
- reject commit or reveal signatures that do not verify against
  `validator_master_key`;
- reject reveals that do not recompute to the committed `commitment_hash`;
- reject commits whose validated ledger close time is outside
  `[commit_opens_at, commit_closes_at)`;
- reject reveals whose validated ledger close time is outside
  `[reveal_opens_at, reveal_closes_at)`;
- order submissions by validated ledger order, using ascending ledger index and
  transaction order within the ledger;
- accept the first valid commit by ledger order for a given
  `protocol_version`, `network`, `round_number`, `input_package_hash`, and
  `validator_master_key`;
- ignore a later valid commit with the same `commitment_hash` and binding
  fields as an idempotent duplicate;
- ignore a later commit with a different `commitment_hash` for verification and
  flag it as a conflicting duplicate;
- accept the first valid reveal by ledger order that matches the accepted
  commit;
- ignore a later valid reveal with the same output hashes and salt as an
  idempotent duplicate;
- reject or flag a later reveal that has different output hashes or salt, or
  does not match the accepted commit;
- keep low participation or divergence separate from canonical VL publication.

The protocol fields above prevent replay across networks, rounds, validators,
input packages, and protocol versions. Binding the preimage to
`validator_master_key` prevents a copied commitment and reveal from verifying as
another validator, while the salt keeps the committed output hashes hidden until
the reveal phase.

## Non-Goals

This specification does not implement or require:

- validator sidecar repository behavior;
- local or validator-owned model inference;
- real validator memo submission;
- chain-history watching or memo ingestion;
- convergence report publication;
- validator output package CIDs;
- additional round lifecycle states such as `ANNOUNCED`, `VERIFICATION_OPEN`,
  or `VERIFICATION_CLOSED`;
- authority transfer away from foundation VL publication.
