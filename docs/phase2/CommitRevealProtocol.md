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

All hashes and signatures should be computed from canonical JSON bytes:

```text
json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
encode as UTF-8
```

The `signature` field is never included in the bytes being signed. Signature
verification must rebuild the same canonical object from the received payload
after removing `signature`.

The hidden commitment hash and the validator signature are separate:

- `commitment_hash` hides the validator's output until the reveal phase.
- `signature` proves which validator authored the public commit or reveal
  payload.

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
  "input_package_hash": "<sha256>",
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
  "input_package_hash": "<sha256>",
  "commitment_hash": "<sha256>",
  "signature": "<hex>"
}
```

The `commitment_hash` is computed from a separate preimage that includes the
future reveal data and salt:

```json
{
  "type": "pf_dynamic_unl_commitment_preimage_v1",
  "protocol_version": 1,
  "network": "testnet",
  "round_number": 123,
  "validator_master_key": "nHU...",
  "input_package_hash": "<sha256>",
  "output_hashes": {
    "model_response_hash": "<sha256>",
    "validator_scores_hash": "<sha256>",
    "selected_unl_hash": "<sha256>"
  },
  "salt": "<validator-generated-random-value>"
}
```

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
  "input_package_hash": "<sha256>",
  "output_hashes": {
    "model_response_hash": "<sha256>",
    "validator_scores_hash": "<sha256>",
    "selected_unl_hash": "<sha256>"
  },
  "salt": "<validator-generated-random-value>",
  "signature": "<hex>"
}
```

The reveal signature is computed over the reveal payload without `signature`.
To validate a reveal, tooling must:

1. verify the reveal signature against `validator_master_key`;
2. rebuild the commitment preimage from the reveal fields;
3. compute the canonical SHA-256 hash of that preimage;
4. compare it to the validator's earlier `commitment_hash`.

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
  "input_package_hash": "<sha256>",
  "final_bundle_cid": "Qm...",
  "participants": [],
  "summary": {}
}
```

Detailed convergence report contents belong to later foundation-service
implementation. This document only reserves the message role and its binding to
the same round and frozen input package.

## Validity Rules

Implementations should apply these rules when protocol helpers and sidecar
logic are added:

- reject payloads with an unsupported `protocol_version` or `type`;
- reject commits or reveals whose `network`, `round_number`, or
  `input_package_hash` does not match the announced round;
- reject commit or reveal signatures that do not verify against
  `validator_master_key`;
- reject reveals that do not recompute to the committed `commitment_hash`;
- reject commits submitted outside the commit window;
- reject reveals submitted outside the reveal window;
- treat duplicate commits or reveals from the same `validator_master_key` as a
  protocol-defined conflict that later implementation must resolve
  deterministically;
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
