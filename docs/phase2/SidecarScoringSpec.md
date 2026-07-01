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

In both modes the sidecar owns the runtime deployment: it deploys the Modal
app or starts the local SGLang container from the round's execution manifest
and records what it deployed in a local `deployment_record.json`. The
manifest compatibility check compares the round's execution manifest against
this local deployment record (see "Deployment Record" below), not against
runtime endpoint APIs. SGLang's `/v1/models` and Modal's OpenAI-compatible
surface do not expose enough metadata (image digest, GPU class, launch args)
for an endpoint-based check to be honest, so the sidecar relies on its own
deploy-time record instead.

## Manifest Compatibility Contract

The sidecar reads the round's `runtime/execution_manifest.json` from the
frozen input package and classifies every field as **required-exact**,
**required-tolerant**, **ignored**, or **conditionally-ignored** based on
mode.

The check is JSON-vs-JSON: the round's execution manifest is compared against
the local `deployment_record.json` that the sidecar wrote when it deployed or
started the runtime. No live endpoint probing is required.

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
| `runtime.kind` | yes (engine match) | The manifest always carries the foundation kind `modal_sglang`; the gate matches on the engine suffix (`sglang`), so a `local` sidecar reproducing the same engine is compatible while a different engine is rejected. Whether the sidecar hosts that engine on Modal or locally is recorded in the deployment record `mode`, not required to match the manifest. |
| `runtime.image` | yes | Includes `@sha256:` digest |
| `runtime.gpu` | yes for `modal`; `local` may be overridden | Override → `local_unverified` |
| `runtime.tensor_parallelism` | yes | Affects determinism |
| `runtime.launch_args` | yes (set of flag/value pairs) | Order-independent; SGLang parses argparse-style. Must include `--enable-deterministic-inference`. |
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

## Deployment Record

The manifest compatibility check is JSON-vs-JSON: it compares the round's
`runtime/execution_manifest.json` against a local
`{data_dir}/runtime/deployment_record.json` that the sidecar writes when it
deploys (Modal mode) or starts (local mode) the runtime. The check never
queries the runtime endpoint for verification because the endpoint's public
APIs do not expose enough metadata to make that check honest.

The deployment record captures:

| Field | Source |
|---|---|
| `mode` | `modal` or `local` |
| `image` | the image string the sidecar pulled or deployed |
| `image_digest` | `docker image inspect` `RepoDigests` (local) or Modal deployed-image inspection (modal) |
| `launch_args` | the exact argv the deploy helper passed |
| `gpu_class` | `nvidia-smi --query-gpu=name --format=csv,noheader` (local) or the Modal GPU type (modal) |
| `tensor_parallelism` | the value the runtime was started with |
| `environment` | the matched subset of `runtime.environment` the runtime was started with |
| `served_model_name` | what the OpenAI-compatible endpoint will serve |
| `model_revision` | the HF commit hash actually downloaded |
| `endpoint_url` | where the sidecar will direct scoring calls |
| `gpu_mismatch_acknowledged` | `true` only if `--allow-gpu-mismatch` was used |
| `deployed_at` | UTC ISO timestamp |

If `deployment_record.json` is missing when the sidecar attempts a score, the
operator gets a clear "no deployment record; run `deploy-modal` or
`start-sglang` first" message. If the record exists but its fields do not
match the round's manifest, the sidecar emits `MANIFEST_INCOMPATIBLE` with
the offending field and instructs the operator to redeploy.

Manual operator deployments outside the sidecar's helpers will fail this
check, which is the right behavior: manual setups are exactly where setup
drift hides.

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

- The sidecar drives Modal deployment via a `deploy-modal --round-id <id>`
  (or `--manifest <path>`) helper that reads the round's execution manifest
  and deploys a Modal app under the operator's account using the manifest's
  pinned image, launch args, GPU class, and environment. The foundation's
  `dynamic-unl-scoring/infra/deploy_qwen36_endpoint.py` is the reference
  deployment script.
- After successful deployment the sidecar writes `deployment_record.json`
  with `mode=modal` (field contract above).
- Scoring config: `--modal-endpoint-url`, plus env-only
  `POSTFIAT_SIDECAR_MODAL_KEY` and `POSTFIAT_SIDECAR_MODAL_SECRET`. Secrets
  accepted only via env, never CLI flag, never logged.
- Submits the frozen `inputs/model_request.json` verbatim through an
  OpenAI-compatible `chat.completions.create` call. All `request.*` fields
  from the manifest flow directly into the call.
- Independence stamp: `modal`.

### Local Mode

- The sidecar drives local startup via a `start-sglang --round-id <id>`
  (or `--manifest <path>`) helper that reads the manifest, calls
  `huggingface_hub.snapshot_download(repo_id, revision)` to populate the HF
  cache, and runs the container with the manifest's pinned image
  (`docker run lmsysorg/sglang:...@sha256:... python -m sglang.launch_server
  <manifest launch args>`).
- After successful startup the sidecar writes `deployment_record.json` with
  `mode=local` (field contract above).
- GPU policy: refuse to start on a non-H100 host unless the operator passes
  `--allow-gpu-mismatch`, which is recorded in the deployment record as
  `gpu_mismatch_acknowledged=true` and downgrades subsequent runs to
  `local_unverified`.
- Scoring config: `--local-endpoint-url` (default
  `http://localhost:8000/v1`).
- Independence stamp: `local` (or `local_unverified` when
  `gpu_mismatch_acknowledged=true`).

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

Each completed sidecar run reports a result for every level it can reproduce,
even when an earlier level already matches, because M2.6 needs multi-level data
to publish meaningful convergence reports. The sidecar never computes
`signed_validator_list` (it does not sign), so at most three levels are
sidecar-comparable.

```text
RAW_MATCH            raw_model_response equal
PARSED_MATCH         validator_scores  equal
SELECTED_UNL_MATCH   selected_unl      equal
DIVERGENT            no level matched; record the level of first divergence
```

Foundation's `outputs/verification_hashes.json` is intentionally unavailable
during the commit window. The foundation publishes final output artifacts only
after `commit_closes_at`, so the sidecar must be able to score, persist its own
hashes, and commit without reading any final-bundle output. In that case the
sidecar records its own hashes and marks the round `SCORED` without comparison
results; comparison is attempted on a later sync pass after output publication.

The sidecar must not treat a missing foundation hash file before commit close as
an error. A 404 is the expected state that proves the hash-withholding boundary
is still intact.

### Output Withholding Watchdog

During each live commit window, the participation loop performs a lightweight
probe for `outputs/verification_hashes.json`. The expected result is 404. If the
scoring service returns the file before `commit_closes_at`, the sidecar records a
protocol violation for operator and campaign reporting because the round's
output hashes were publicly obtainable before validators had to commit.

This watchdog does not run inference and does not require Modal credentials. It
only needs the scoring-service API URL and the round metadata already used by
the normal participation loop.

### Reproducibility and phased rollout

`raw_model_response` and `validator_scores` are fully reproducible from the
frozen input package: the raw response comes from running the frozen
`inputs/model_request.json`, and the parsed scores come from applying the
vendored parser to that response with the frozen `inputs/validator_map.json`.

`selected_unl` is also reproducible from the frozen package. UNL selection
applies churn control against the previous round's UNL, and that UNL is now
frozen into the input package as `inputs/previous_unl.json` (an empty list for
the first round). The foundation's normal-round selection consumes this frozen
value rather than a live database read, so a sidecar that runs its vendored
selector with the frozen scores, the frozen selector parameters from
`runtime/execution_manifest.json`, and the frozen previous UNL reproduces the
foundation's `outputs/selected_unl.json` exactly.

The sidecar can therefore report all three levels — `raw_model_response`,
`validator_scores`, and `selected_unl`. Because the lower levels are
deterministic functions of the raw response, a `RAW_MATCH` already implies the
others; the separate `validator_scores` level still earns its place by
confirming agreement when the raw text diverges only in benign formatting the
parser normalizes away.

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
- **Mid-run mutation detection.** If the operator stops or reconfigures the
  runtime outside the sidecar's deploy helpers, `deployment_record.json`
  becomes stale and the next round's compat check passes spuriously against
  an outdated record. Options for catching this: best-effort re-probe of
  `served_model_name` via `/v1/models` each run, periodic forced redeploy,
  or relying on operator discipline plus clear documentation. Decide during
  devnet validation.

## Decision Summary

- Vendor parser and selector at a pinned version; refuse unsupported
  versions.
- Two backend modes (`modal`, `local`), both genuinely independent of the
  foundation. No shared-endpoint mode; the foundation endpoint stays closed.
- The sidecar owns the runtime deployment in both modes; the compatibility
  check is JSON-vs-JSON between the round's execution manifest and a local
  `deployment_record.json`, not endpoint probing.
- `runtime.launch_args` matched as a set of flag/value pairs, not as an
  ordered list, since SGLang behavior is order-independent.
- Manifest fields classified explicitly; mode downgrades on operator
  override are recorded as `local_unverified` with
  `gpu_mismatch_acknowledged=true` in the deployment record, never silent.
- Four comparison hashes published locally per round; convergence is
  multi-level, not pass/fail.
- One failure enum shared with M2.6.
- Schema v2 is additive; the M2.1 cache contract is unchanged.
