# Sidecar Scoring Spec

This document is the M2.4 contract for validator-side scoring: how a sidecar
matches the foundation's execution setup, how it runs its own inference
against a frozen input package, how it normalizes outputs for comparison, and
how it classifies divergence and failure.

It is a design and contract document. It does not change scoring-service
behavior, foundation artifact publication, on-chain memo flow, or Validator
List authority. The implementation work belongs to
`validator-scoring-sidecar`.

## Purpose

Phase 2 verification requires the foundation scorer and validator sidecars to
score the same frozen input under setups close enough that any output
difference is attributable to scoring divergence, not setup drift.

Three questions must be answered concretely before sidecar inference starts:

- Which manifest fields must match exactly, which may warn, which may be
  ignored, and how does that depend on the sidecar's backend mode.
- Which canonical hashes the sidecar computes locally and compares against the
  foundation's `outputs/verification_hashes.json`.
- Which failure categories the sidecar emits, so M2.6 convergence reports can
  speak a shared vocabulary.

## Scope

In scope:

- Manifest compatibility checking on the sidecar side.
- Two backend modes: validator-owned Modal/SGLang endpoint, validator-owned
  local SGLang.
- Output canonicalization and comparison-level definitions.
- Failure taxonomy reused by M2.4 and M2.6.
- SQLite state additions for the scoring stage.

Out of scope (covered later):

- Round announcement watching, commit/reveal memo submission, wallet handling
  (M2.5).
- Foundation-side ingestion of validator outputs and publication of
  convergence reports (M2.6).
- Operator onboarding documentation (M2.7).
- Validator List authority changes (Phase 3+).

## Backend Modes

Sidecar inference runs in one of two modes. Both are genuinely independent
from the foundation: there is no shared-endpoint fallback. The foundation
Modal endpoint is closed and only callable with foundation credentials, so
external sidecars cannot use it as a smoke-test path. The mode is stamped on
every run for convergence reports.

| Mode | Backend | Typical operator |
|---|---|---|
| `modal` | Validator-owned Modal account running the same SGLang image | Operators who prefer managed infra |
| `local` | Validator-owned local SGLang on operator hardware | Operators with H100-class GPUs |

A sidecar may not advertise a mode whose manifest checks it skipped.
Operator-chosen overrides (for example running `local` on a non-H100) are
recorded as `local_unverified` so convergence reports stay honest.

## Manifest Compatibility Contract

The sidecar reads the round's `runtime/execution_manifest.json` from the
frozen input package and classifies every field as **required-exact**,
**required-tolerant**, **ignored**, or **conditionally-ignored** based on
mode.

### Normal Rounds

| Field | Required-exact | Notes |
|---|---|---|
| `schema_version` | yes | Unsupported version → `MANIFEST_UNSUPPORTED` |
| `round.kind` | yes | Must be `normal` for the inference path |
| `round.network` | yes | Sidecar's configured network must match |
| `round.round_number` | yes | Cross-checked against scoring-service round metadata |
| `round.inference_performed` | yes | Must be `true` for normal |
| `model.provider` | yes | |
| `model.repo_id` | yes | |
| `model.revision` | yes | Full HF commit hash; branch names are rejected |
| `model.served_name` | yes | Sent verbatim as OpenAI `model` value |
| `runtime.kind` | yes | Sidecar advertises `modal_sglang` for `modal` mode, `local_sglang` for `local` mode |
| `runtime.image` | yes | Includes `@sha256:` digest |
| `runtime.gpu` | yes for `modal`; `local` may be overridden | Override → `local_unverified` |
| `runtime.tensor_parallelism` | yes | Affects determinism |
| `runtime.launch_args` | yes | Must contain `--enable-deterministic-inference` |
| `runtime.environment.SGLANG_FLASHINFER_WORKSPACE_SIZE` | yes | Required for the ~8K-token scoring prompt |
| `runtime.environment.*` other keys | ignored | Not behavior-affecting in current runtime |
| `request.type` | yes | |
| `request.method` | yes | |
| `request.model` | yes | Must equal `model.served_name` |
| `request.temperature` | yes | Must be `0` |
| `request.max_tokens` | yes | |
| `request.response_format` | yes | |
| `request.extra_body` | yes | Includes Qwen non-thinking flag |
| `request.timeout_seconds` | tolerant | Sidecar may set its own value ≥ this |
| `code.parser` | yes | Sidecar's vendored parser version must match |
| `code.selector` | yes | Sidecar's vendored selector + params must match |
| `code.collector` | ignored | Collection happened before `INPUT_FROZEN` |
| `code.vl_generator` | ignored | Foundation-only; sidecar does not sign |
| `code.repository` / `code.commit` | required, informational | Recorded for the convergence report; not behavior-affecting beyond parser/selector |
| `canonicalization` | yes | Sidecar hashes outputs using the same rule |

### Override Rounds

`round.kind == "override"` and `round.inference_performed == false`. Sidecar
skips inference and emits `SKIPPED_OVERRIDE`. No comparison hashes are
computed. The sidecar still records the round in its SQLite state and verifies
the input package signature/hash chain as usual.

### Dry-Run Rounds

Sidecars do not score dry-run rounds. Dry-run bundles are private foundation
artifacts and are not exposed through the public round list the sidecar
syncs. If a sidecar somehow encounters one, it emits `SKIPPED_OPERATOR_OPT_OUT`
with reason `dry_run`.

## Code Reuse Strategy

The parser and selector outputs must be byte-identical to the foundation's
for parsed-score and selected-UNL comparisons to be meaningful. Re-implementing
them from spec defeats the purpose of verification — the comparison would
detect our own re-implementation drift, not foundation divergence.

**Decision:** vendor the parser and selector into the sidecar repository at a
pinned version.

```text
validator-scoring-sidecar/src/validator_scoring_sidecar/scoring/
├── __init__.py
├── parser.py       # vendored from scoring_service/services/response_parser.py
└── selector.py     # vendored from scoring_service/services/unl_selector.py
```

Vendoring requires light adaptation:

- Drop `from scoring_service.config import settings`; selector parameters are
  passed in explicitly from the manifest's
  `code.selector.parameters` (`score_cutoff`, `max_size`, `min_score_gap`).
- Drop the `ValidatorIdentityMap` import; parser takes the dict directly,
  built from the frozen `inputs/validator_map.json`.
- No other behavior changes. The vendor target is byte-identical
  parsed-score and selected-UNL output.

Pin a `SCORING_CODE_VERSION` constant in `validator_scoring_sidecar.scoring`
that records the foundation commit the vendored code was lifted from. The
manifest compatibility check fails closed if the round's `code.parser.version`
or `code.selector.version` is not in the sidecar's supported set.

Refresh procedure: when foundation updates parser or selector, vendor the new
copy under a new `SCORING_CODE_VERSION`, keep the previous version supported
until the last devnet/testnet round on the old version has been verified,
then drop the old vendor.

Alternatives considered and rejected:

- **Depend on `dynamic-unl-scoring` as a library.** Foundation repo bundles
  service code (FastAPI, Postgres, Modal clients, prompt templates) the
  sidecar does not need and should not link.
- **Re-implement from spec.** Two implementations of the same parser is
  exactly what verification is meant to detect; we would chase our own drift.

## Backend Implementation Notes

### Modal Mode

- Operator deploys their own Modal app using
  `dynamic-unl-scoring/infra/deploy_qwen36_endpoint.py` (or pinned
  equivalent) under their own Modal account.
- Sidecar config: `--modal-endpoint-url`, plus env-only
  `POSTFIAT_SIDECAR_MODAL_KEY` and `POSTFIAT_SIDECAR_MODAL_SECRET`. Secrets
  accepted only via env, never CLI flag, never logged.
- Submits the frozen `inputs/model_request.json` verbatim through an
  OpenAI-compatible `chat.completions.create` call. All `request.*` fields
  from the manifest flow directly into the call.
- Health probe at sidecar start (when feasible) compares `runtime.image`
  digest and `runtime.gpu` against the operator endpoint's `/health` and
  `/v1/models` responses.
- Independence stamp: `modal`.

### Local Mode

- Operator runs SGLang locally with the manifest-pinned image and launch args.
  Sidecar binds to `--local-endpoint-url` (default
  `http://localhost:8000/v1`).
- GPU check: the sidecar refuses to start a comparison run on a non-H100 host
  unless the operator explicitly passes `--allow-gpu-mismatch`, which
  downgrades the run to `local_unverified`.
- A `warm-model` helper command downloads the manifest-pinned snapshot via
  `huggingface_hub.snapshot_download(repo_id, revision)` into the operator's
  HF cache before the first round.
- Storage and runtime budget are operator concerns; the sidecar documents
  the manifest's GPU/memory expectations but does not manage them.
- Independence stamp: `local` (or `local_unverified` if overridden).

## Output Normalization and Comparison

The sidecar computes the same canonical hashes the foundation publishes in
`outputs/verification_hashes.json`. Canonical JSON encoding follows the
manifest's `canonicalization` block:

```python
json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
sha256(utf8_bytes).hexdigest()
```

### Comparison Targets

| Hash name | Source on sidecar | Foundation source | Meaning of a match |
|---|---|---|---|
| `raw_model_response` | sidecar's own raw response text wrapped in the foundation `model_response` envelope | `outputs/model_response.json` | Byte-identical inference output — strongest match, requires full determinism |
| `validator_scores` | sidecar parser output | `outputs/validator_scores.json` | Parsed-score agreement independent of raw text formatting |
| `selected_unl` | sidecar selector output | `outputs/selected_unl.json` | UNL selection agreement |
| `signed_validator_list` | not computed | `outputs/signed_validator_list.json` | Foundation-only; sidecar does not sign |

The sidecar persists its own
`{data_dir}/scored/{input_package_hash}/verification_hashes.json` for
operator inspection, alongside the verified input package cache. The cache
contract from M2.1 is unchanged; this is a new sibling directory.

### Comparison Levels

Each completed sidecar run reports four results, even when an earlier level
already matches. M2.6 needs multi-level data to publish meaningful
convergence reports.

```text
RAW_MATCH            raw_model_response equal
PARSED_MATCH         validator_scores  equal
SELECTED_UNL_MATCH   selected_unl      equal
DIVERGENT            no level matched; record the level of first divergence
```

Foundation's `outputs/verification_hashes.json` may not be available at the
moment the sidecar finishes scoring — the foundation publishes it only after
its own scoring completes. In that case the sidecar records its own hashes
and marks the round `SCORED` without comparison results; the comparison is
attempted on a later sync pass once the foundation final bundle exists.

## Failure Taxonomy

One enum, used by M2.4 (sidecar local state) and M2.6 (foundation convergence
report). Each value is structured: `category` plus optional `field`,
`message`, and `comparison_results`.

| Category | When emitted |
|---|---|
| `MANIFEST_UNSUPPORTED` | schema_version or fields not understood by this sidecar version |
| `MANIFEST_INCOMPATIBLE` | required-exact field mismatch; `field` names the field |
| `RUNTIME_UNAVAILABLE` | endpoint unreachable, image pull failed, GPU not present |
| `INFERENCE_TIMEOUT` | request timeout |
| `INFERENCE_ERROR` | non-timeout API or SGLang error |
| `PARSER_ERROR` | vendored parser rejected the sidecar's own raw response |
| `SELECTOR_ERROR` | vendored selector failed on parsed scores |
| `OUTPUT_DIVERGENCE` | hashes computed; one or more comparison levels failed; payload carries per-level results |
| `SKIPPED_OVERRIDE` | round.kind == override, no inference attempted |
| `SKIPPED_OPERATOR_OPT_OUT` | manifest valid but operator chose to skip (e.g. model snapshot unavailable, low Modal balance, dry-run) |
| `REVEAL_WINDOW_MISSED` | reserved for M2.5; not emitted by M2.4 directly |

`MANIFEST_INCOMPATIBLE` always carries the specific field name in
`details.field`. Operators must be able to fix configuration without reading
sidecar source.

## Sidecar State Additions

M2.4 bumps SQLite schema to v2 with an additive migration. New states added
to `sidecar_rounds.sidecar_state`:

```text
SCORED            sidecar produced its own outputs and hashes
SCORING_FAILED    sidecar attempted inference and failed; see error_category
SKIPPED           override or operator opt-out
```

New columns:

```text
scored_at                  TEXT (UTC ISO)
backend_mode               TEXT (modal | local | local_unverified)
raw_response_hash          TEXT
validator_scores_hash      TEXT
selected_unl_hash          TEXT
comparison_levels_matched  TEXT (comma-separated: RAW,PARSED,SELECTED_UNL)
error_category             TEXT (failure taxonomy value)
error_details              TEXT (JSON blob)
```

Existing `INPUT_PACKAGE_VERIFIED` rounds are not touched by the migration;
new columns default to NULL. The sync command's "round already handled"
predicate becomes order-aware: any state at or beyond `INPUT_PACKAGE_VERIFIED`
counts as input-ready.

## Open Questions

- **Non-H100 determinism.** Is byte-identical Qwen3.6-27B-FP8 inference under
  `--enable-deterministic-inference` achievable on other GPU classes? If yes,
  the `local` mode GPU lock can broaden over time. If not, document the H100
  requirement in the operator guide and keep `--allow-gpu-mismatch` as the
  honest opt-out.
- **Foundation hashes availability timing.** Cleanest default is for the
  sidecar to attempt comparison on the next sync pass after the foundation
  final bundle exists. An alternative is to subscribe to the M2.2 round
  announcement memo (M2.5) for an explicit signal. Defer to M2.5 design.
- **Model snapshot byte-level verification.** Manifest pins
  `model.revision`. If future logit-proof work demands per-file hashes, add
  a separate `model_snapshot.json` per the manifest doc; the sidecar's
  compatibility checker grows a new field then.
- **Vendored code drift cadence.** How often is foundation parser/selector
  expected to change? Drives the version-support window. Resolve once
  M2.4 has run on devnet for a few rounds.

## Decision Summary

- Vendor parser and selector at a pinned version; refuse unsupported
  versions.
- Two backend modes (`modal`, `local`), both genuinely independent of the
  foundation. No shared-endpoint mode; the foundation endpoint stays closed.
- Manifest fields classified explicitly; mode downgrades on operator override
  are recorded as `local_unverified`, never silent.
- Four comparison hashes published locally per round; convergence is
  multi-level, not pass/fail.
- One failure enum shared with M2.6.
- Schema v2 is additive; the M2.1 cache contract is unchanged.
