# Convergence Reporting

The durable design record for the foundation-side convergence-monitoring system
delivered in Milestone 2.6. It documents how the scoring service ingests
validator commit and reveal memos from the PFT Ledger, verifies each committer's
participation, compares revealed output hashes against the foundation's own,
seals a per-round convergence report, anchors it on chain, and serves it over
HTTP.

This is the "later foundation-service implementation" that
[`CommitRevealProtocol.md`](CommitRevealProtocol.md) reserves the convergence
report message role for. That document and [`SidecarScoringSpec.md`](SidecarScoringSpec.md)
remain the source of truth for the wire protocol (message types, canonical
payloads, validity rules, timing and ledger order) and the shared failure
taxonomy; this document does not restate them, it describes the foundation
service built on top of them. Where this document and the running code disagree,
the code wins — every field, value, level, phase, and memo type below was
reconciled against the shipped implementation, not the original plan.

## Trust and Authority Boundary

Convergence monitoring is strictly **read-only with respect to canonical
Validator List publication**. It never blocks, delays, or alters the scored UNL,
the signed VL, or its distribution. Low participation, missed reveals,
conflicting duplicates, and divergent output hashes are recorded as evidence for
monitoring and debugging only. Final output publication is held until the commit
window closes so validators cannot copy foundation hashes into their commits;
the later convergence report still seals and anchors on a schedule decoupled
from VL publication, so a slow or empty reveal phase never holds up the
canonical VL after the commit-close boundary. This boundary matches the Phase 2 fallback
boundary in [`CommitRevealProtocol.md`](CommitRevealProtocol.md); this document
defines no participation thresholds, convergence percentages, rollout gates,
fallback triggers, or authority-transfer criteria — those require live
devnet/testnet evidence and belong to later milestones.

## Data Flow

```text
┌──────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ PFTL account_tx      │   │ Verification           │   │ Sealed report            │
│ commit / reveal /    │──▶│ - accept first-valid   │──▶│ convergence_report.json  │
│ announcement memos   │   │ - verify signatures    │   │ pinned (IPFS + Pinata)   │
│ → validator_commits  │   │ - recompute commitment │   │ anchored on chain        │
│ → validator_reveals  │   │ - compare output hashes│   │ + DB row (HTTPS fallback)│
│ → round_announcements│   │ → validator_round_     │   └──────────────────────────┘
└──────────────────────┘   │   outcomes             │              │
                          └───────────────────────┘              ▼
                                     ▲                  GET /api/scoring/...
                                     │                  /convergence (live | sealed)
                            live re-verification
                            until the round seals
```

Ingestion runs as its own background loop (`convergence_ingestion_loop`, started
in `scoring_service/main.py`), independent of the scoring scheduler. Verification
and sealing are driven from that loop; the API reads the resulting state.

## Participation Ingestion

A chain watcher polls `account_tx` for the foundation publisher account. Every
validator commit and reveal Payment targets that address as its destination, so a
single account scan surfaces all participants alongside the foundation's own
round-announcement memos.

`decode_transaction` turns each `account_tx` entry into zero or more records. It
resolves the memo `MemoType` to a known kind (commit, reveal, or announcement),
requires the decoded `MemoData` to be a JSON object carrying an integer
`round_number`, and captures the validated-ledger position — `ledger_index`,
in-ledger `TransactionIndex`, and ledger close time — so downstream window
evaluation is deterministic and independent of poll or wall-clock time.

Records are persisted at per-transaction grain:

| Table | Key | Notes |
|-------|-----|-------|
| `validator_commits` | `tx_hash` (PK) | One row per commit memo; indexed by `(round_number, validator_master_key)` and by ledger order. Stores the full decoded `payload`. |
| `validator_reveals` | `tx_hash` (PK) | One row per reveal memo; carries the three output hashes and `salt`. |
| `round_announcements` | `round_number` (PK) | The foundation's announced window boundaries; first announcement by ledger order wins. |
| `convergence_ingestion_cursor` | `account` (PK) | Highest ledger index already scanned, so each pass resumes forward. |

All inserts are idempotent (`ON CONFLICT DO NOTHING`), so overlapping scans are
safe and re-ingesting the same `tx_hash` is a no-op. Ingestion deliberately
keeps **every** memo that decodes as a known type for a known round, including
well-formed but invalid submissions (bad signature, commitment mismatch, late,
or duplicate). Validity bucketing belongs to verification; filtering at ingest
would erase the divergence and abuse signals the report exists to surface.
Keeping one row per submission (rather than collapsing to one per validator)
preserves conflicting duplicates for first-valid-by-ledger-order selection.

The per-round commit and reveal windows are **not derivable from current config**
— they are anchored to announcement-emission time — so the announcement is the
only authoritative source for them, which is why it is ingested and persisted
alongside the submissions.

## Observed-Committer Population

Phase 2 participation is open: any validator may participate, and there is no
foundation-published roster of expected participants. The report's population is
therefore the set of validators **observed committing on chain** for the round.
Each observed committer is classified; a validator that never committed simply
does not appear.

`missing_commit` is intentionally **not** a current outcome — it presupposes an
expected validator set to be "missing" from. It is reserved for later phases that
introduce such a roster. This refines the minimal expected-validator sketch in
[`CommitRevealProtocol.md`](CommitRevealProtocol.md): the shipped taxonomy below
is the superset that open participation actually produces.

## Per-Round Response Contract

The convergence state of a round is exposed in one stable shape, discriminated by
a `phase` / `finalized` pair, through two read-only endpoints keyed on the
on-chain `round_number`:

- `GET /api/scoring/rounds/{round_number}/convergence`
- `GET /api/scoring/convergence/current` — resolves the latest announced round so
  callers need no round id.

| `phase` | `finalized` | Meaning | Source |
|---------|-------------|---------|--------|
| `live` | `false` | Round announced, not yet sealed | Live tally assembled from `validator_round_outcomes` |
| `sealed` | `true` | Report finalized | The immutable stored `report`, served verbatim alongside its `convergence_bundle_cid`, `anchor_tx_hash`, and `sealed_at` |
| `not_tracked` | `false` | Round outside convergence monitoring (override, not-yet-announced, or pre-protocol) | — |

The endpoints key on the on-chain `round_number`, not the service's internal
database id, to stay consistent with every convergence table and the audit-trail
fallback routes. A sealed round is served from stored content and **never
recomputed**, so the response matches the pinned `convergence_bundle_cid` and its
on-chain anchor exactly. An existing round with no convergence data returns
`200` with `phase: not_tracked`; a round number that was never scored returns
`404`. Responses carry `Cache-Control` headers derived from `finalized` —
`immutable` once sealed, a short `max-age` while live — with no server-side
cache. The routes live in their own router registered ahead of the audit-trail
`/rounds/{n}/{file_path:path}` catch-all so the per-round path is not shadowed.

## Participation Verification and Outcome Taxonomy

For each round that has an ingested announcement and at least one commit, and is
not yet sealed, every observed committer is (re)classified and the result is
upserted into `validator_round_outcomes`. A round is re-verified as new
submissions arrive and stops being re-verified once it seals. Ingestion remains
permissive: mismatched commits and reveals are stored as raw evidence, while
announcement binding is enforced only in verification.

The commitment and signature cryptography is **not reimplemented**: the shared
`commit_reveal` module is reused verbatim — the same module the validator sidecar
vendors — so both sides agree exactly on what a valid submission is. For each
validator the accepted commit and reveal are the **first valid ones by
validated-ledger order** after applying the classification precedence:
signature validity, window membership, announcement binding, reveal-to-commit
binding, then foundation-hash comparison. Announcement binding means the commit
or reveal must match the announcement's `protocol_version`, `network`,
`round_number`, and `input_package_hash`. Window membership uses half-open
intervals (`opens_at <= close_time < closes_at`) evaluated against each
submission's captured ledger close time. Conflicting same-validator submissions
are flagged (`conflicting_commit` / `conflicting_reveal`), not dropped.

| Outcome | Meaning |
|---------|---------|
| `valid` | First valid reveal matched its commitment; the acceptance-level hashes (`RAW`, `PARSED`) matched the foundation (or could not be compared because foundation hashes were absent). A `SELECTED_UNL`-only mismatch is diagnostic, not divergence — see Output Comparison. |
| `divergent` | Reveal accepted, but an acceptance-level output hash (`RAW` or `PARSED`) diverged from the foundation. |
| `missing_reveal` | A valid commit was accepted, but no valid reveal was. |
| `awaiting_reveal` | Live API label only: a valid commit exists and the reveal window is still open. Sealed reports use `missing_reveal` if no valid reveal arrives. |
| `late` | A signed commit exists, but none fell inside the commit window. |
| `announcement_mismatch` | A signed, in-window commit or reveal was bound to a different protocol version, network, round, or input package than the round announcement. |
| `commitment_mismatch` | A reveal was seen, but none recomputed to the accepted commitment. |
| `signature_invalid` | No commit carried a valid master-key signature. |

Mapping to the conceptual outcomes reserved in
[`CommitRevealProtocol.md`](CommitRevealProtocol.md): `revealed` splits into
`valid` and `divergent`; `missing_reveal` is unchanged; `awaiting_reveal` is a
live rendering of a not-yet-terminal `missing_reveal`; `announcement_mismatch`,
`late`, `commitment_mismatch`, and `signature_invalid` are finer buckets of what
the sketch grouped as a non-accepted submission; `missing_commit` is reserved
(see Observed-Committer Population).

## Output Comparison

Comparison is **hashes only**. The v1 reveal memo carries the three reproducible
output hashes directly — `model_response_hash`, `validator_scores_hash`,
`selected_unl_hash` — and no URL or CID. For an accepted reveal, each is compared
to the foundation's own `outputs/verification_hashes.json` at three levels, named
to match the shared taxonomy in [`SidecarScoringSpec.md`](SidecarScoringSpec.md):

| Level | Compares | Role |
|-------|----------|------|
| `RAW` | Raw model response | Acceptance |
| `PARSED` | Parsed validator scores | Acceptance |
| `SELECTED_UNL` | Selected UNL | Diagnostic |

Participant validity is judged on the acceptance levels only — the LLM-output
levels that require an actual model rerun on the pinned runtime to reproduce.
Everything after the parser is deterministic and publicly recomputable from the
round artifacts, so the `SELECTED_UNL` hash is diagnostic: a mismatch shows as
the level missing from `comparison_levels_matched` on a `valid` outcome and
localizes a divergence to the deterministic tail (for example a sidecar whose
vendored selection predates the deterministic final-score stage — see
`docs/DeterministicFinalScore.md`), but cannot cause one. Sealed reports carry
an `acceptance_levels` field so consumers can tell which rule sealed them;
reports sealed before this field existed used all three levels for acceptance.

`signed_validator_list` is foundation-only and not reproduced by sidecars, so it
is not a convergence level. Divergence requires positive evidence: if a
foundation hash (or a level) is absent, that level is treated as not-comparable
rather than divergent, so an unpublished foundation artifact never yields a false
divergence. Each outcome records `comparison_levels_matched` (comma-joined
levels), the first `divergence_stage`, and the `divergence_category`, which is
`OUTPUT_DIVERGENCE` from the shared taxonomy when an acceptance level diverges.

Foundation hashes are expected to be absent before `commit_closes_at`; the final
bundle and its output fallback routes are published only after that boundary.
Live convergence during the commit window therefore reports participation state,
not output comparison.

### Settled decision: hashes-only, full-output publication deferred

Phase 2 convergence is established from the on-chain output hashes alone. This is
sufficient for the convergence verdict — whether a validator reproduced the
foundation's outputs. Whether validators should additionally publish a **full
output bundle** (for example IPFS-pinned, referenced by a CID in an extended
reveal payload) so the foundation and third parties can inspect *why* a validator
diverged is a deliberate protocol extension, **deferred** as future work. It is
not part of M2.6: it would change the reveal payload (a `commit_reveal` and
on-chain protocol change) and place a pinning burden on every validator, for a
benefit — root-cause inspection of divergence — that the hashes-only verdict does
not require. The hashes-only design is the settled Phase 2 position.

## Report Shape

The sealed report is the JSON object assembled from the stored outcomes:

```json
{
  "type": "pf_dynamic_unl_convergence_report_v1",
  "protocol_version": 1,
  "network": "devnet",
  "round_number": 273,
  "input_package_hash": "<64 lowercase hex sha256>",
  "input_package_cid": "Qm...",
  "participants": [
    {
      "validator_master_key": "nH...",
      "outcome": "valid",
      "accepted_commit_tx": "<tx hash>",
      "accepted_reveal_tx": "<tx hash>",
      "conflicting_commit": false,
      "conflicting_reveal": false,
      "comparison_levels_matched": "RAW,PARSED,SELECTED_UNL",
      "divergence_stage": null,
      "divergence_category": null
    }
  ],
  "summary": {
    "committers": 1,
    "outcomes": {"valid": 1},
    "levels_matched": {"RAW": 1, "PARSED": 1, "SELECTED_UNL": 1},
    "divergence_categories": {}
  }
}
```

The report binds to the round's frozen input package via `input_package_hash` and
`input_package_cid`. It carries no `final_bundle_cid`: the report is published as
its own content-addressed bundle and anchored by a separate
`convergence_bundle_cid` (below), which is what the conceptual sketch in
[`CommitRevealProtocol.md`](CommitRevealProtocol.md) anticipated as the report's
own reference.

## Sealing Lifecycle

A round becomes sealable once the latest validated ledger has closed past
`reveal_closes_at` plus a grace period. The grace is
`max(convergence_seal_grace_floor_seconds, convergence_seal_grace_fraction × reveal_window)`,
so short devnet windows stay usable. The deadline is evaluated against
**validated-ledger close time**, not wall-clock, so the foundation and validators
agree on when the round closed.

Sealing is a one-time finalization driven from the watcher loop:

1. Assemble the report from the stored outcomes.
2. Pin it as its own bundle, producing `convergence_bundle_cid`.
3. Insert into `convergence_reports` — seal-once is enforced by the
   `round_number` primary key.
4. Anchor it on chain.

A sealed round drops out of live re-verification, and submissions that arrive
after the seal are dropped rather than triggering a re-pin. If a round is sealed
but its on-chain anchor never landed, a later pass re-anchors it without
re-pinning (pinning the same content is a no-op, and a duplicate anchor is never
submitted for an already-anchored round). Sealing is fully decoupled from
canonical VL publication.

## Report Bundle Publication and Durability

The sealed report is pinned as a single-file directory
(`convergence_report.json`) whose root CID is the `convergence_bundle_cid`,
mirroring the final-audit-bundle durability pattern: a primary IPFS pin plus a
secondary Pinata replication (pin name `dynamic-unl-convergence-round-{round_number}`).
The full report is also stored in the `convergence_reports` row as JSONB, which
backs the HTTPS fallback the API serves for a sealed round.

## On-Chain Anchoring

Each sealed report is anchored by a `pf_dynamic_unl_convergence_report_v1` memo
submitted from the foundation publisher account. The memo is a **pointer only**:

```json
{
  "type": "pf_dynamic_unl_convergence_report_v1",
  "round_number": 273,
  "convergence_bundle_cid": "Qm..."
}
```

Per-validator outcomes and the summary live in the pinned bundle, not the memo.
This mirrors the round-announcement and final-receipt memos and lets any third
party scanning the publisher account resolve a round to its sealed convergence
report.

## Storage Schema

| Migration | Adds |
|-----------|------|
| `013_commit_reveal_ingestion.sql` | `validator_commits`, `validator_reveals`, `convergence_ingestion_cursor` |
| `014_convergence_verification.sql` | `round_announcements`, `validator_round_outcomes` |
| `015_per_level_convergence.sql` | per-level comparison columns on `validator_round_outcomes` |
| `016_convergence_reports.sql` | `convergence_reports` (sealed report, CID, anchor tx, JSONB body) |

## Module Reference

| Concern | Module |
|---------|--------|
| Ingestion loop, decode, persistence | `scoring_service/services/convergence_ingestion.py` |
| Verification, comparison, report assembly, sealing | `scoring_service/services/convergence_verification.py` |
| Shared commit/reveal crypto and memo types | `scoring_service/services/commit_reveal.py` |
| Report bundle pinning | `scoring_service/services/ipfs_publisher.py` (`publish_convergence_report`) |
| On-chain anchor memo | `scoring_service/services/onchain_publisher.py` (`publish_convergence_report`) |
| Read-only API | `scoring_service/api/convergence.py` |
