# Scoring Service Operations Guide

Operations reference for the Dynamic UNL Scoring service on devnet and testnet.

## How the Pipeline Works

The scoring service evaluates PFT Ledger validators and publishes a signed Validator List (VL) that determines which validators are trusted for consensus. A single scoring round progresses through eight stages:

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  ┌──────────────┐   VHS validators   ┌────────────────┐            │
│  │              │◄── VHS topology ───│  External      │            │
│  │  1. COLLECT  │◄── /crawl IPs   ───│  Data Sources  │            │
│  │              │◄── ASN + GeoIP  ───│                │            │
│  └──────┬───────┘                    └────────────────┘            │
│         │ snapshot.json                                            │
│         ▼                                                          │
│  ┌──────────────┐   anonymized       ┌────────────────┐            │
│  │  2. SCORE    │── profiles ───────►│  Modal LLM     │            │
│  │              │◄── scores ─────────│  (Qwen3 80B)   │            │
│  └──────┬───────┘                    └────────────────┘            │
│         │ scores.json                                              │
│         ▼                                                          │
│  ┌──────────────┐                                                  │
│  │  3. SELECT   │── cutoff ≥ 40, max size, churn control           │
│  └──────┬───────┘                                                  │
│         │ unl.json                                                 │
│         ▼                                                          │
│  ┌──────────────┐   manifests        ┌────────────────┐            │
│  │  4. VL SIGN  │◄── from RPC ───────│  postfiatd     │            │
│  │              │   secp256k1 sig    │  RPC node      │            │
│  └──────┬───────┘                    └────────────────┘            │
│         │ vl.json → served at /vl.json                             │
│         ▼                                                          │
│  ┌──────────────┐   pin directory   ┌────────────────┐             │
│  │              │──────────────────►│  Primary IPFS  │             │
│  │  5. IPFS     │   pin-by-CID      ├────────────────┤             │
│  │              │──────────────────►│  Pinata        │             │
│  └──────┬───────┘                   └────────────────┘             │
│         │ metadata.json (hashes, gateways, attribution)            │
│         ▼                                                          │
│  ┌──────────────┐   Contents API    ┌───────────────────────────┐  │
│  │  6. DISTRIB  │── commit VL ─────►│  postfiatorg.github.io    │  │
│  │              │                   │  → postfiat.org/*.vl.json │  │
│  └──────┬───────┘                   └───────────────────────────┘  │
│         │ github_pages_commit_url                                  │
│         ▼                                                          │
│  ┌──────────────┐   1-drop Payment   ┌────────────────┐            │
│  │  7. ON-CHAIN │── + memo ─────────►│  PFT Ledger    │            │
│  └──────┬───────┘                    └────────────────┘            │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────┐                                                  │
│  │  8. COMPLETE │── round finalized, all artifacts persisted       │
│  └──────────────┘                                                  │
│                                                                    │
│  Any stage failure → round marked FAILED                           │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Each stage produces artifacts that are persisted in PostgreSQL and served via public API endpoints. If any stage fails, the round is marked `FAILED`. Failures before VL sequence confirmation release the reservation for reuse; failures after `VL_SIGNED` may leave the signed VL and confirmed sequence persisted for audit/debugging even though canonical GitHub Pages distribution did not complete.

**VL distribution path.** Validators consume their signed VL from `postfiat.org/{env}_vl.json`, which is served by GitHub Pages from `postfiatorg/postfiatorg.github.io`. Stage 6 `VL_DISTRIBUTED` uses the GitHub Contents API to commit the newly-signed VL to the repo at the configured path (`devnet_vl.json` or `testnet_vl.json`). Pages rebuilds within 1-2 minutes of the commit, which is well inside the default 1-hour `effective_lookahead_hours`, so every validator's next poll-interval fetch (default 5 minutes) picks up the pending blob and caches it for simultaneous activation at the scheduled effective time. The scoring service also continues to serve a live copy at `/vl.json` on its own domain (`scoring-{env}.postfiat.org/vl.json`) for tooling and debugging, but validators do not consume this endpoint.

**Artifacts per round:**

| File | Contents |
|---|---|
| `snapshot.json` | Normalized validator evidence used to render the prompt, including keys/IPs for audit |
| `prompt.json` | Exact OpenAI-compatible `messages` array sent to the scoring model |
| `validator_id_map.json` | Anonymous prompt IDs mapped to validator master and signing keys |
| `raw_response.json` | Raw unparsed model response consumed by the response parser |
| `scores.json` | Output from the LLM: overall + 5 dimension scores, per-validator reasoning, network summary |
| `unl.json` | Selected UNL validators + alternates |
| `vl.json` | Signed Validator List (v2 format, served at `/vl.json`) |
| `metadata.json` | Round metadata: file hashes, gateway URLs, DB-IP attribution |

---

## Environments

| | Devnet | Testnet |
|---|---|---|
| Scoring service | `scoring-devnet.postfiat.org` | `scoring-testnet.postfiat.org` |
| RPC node | `rpc.devnet.postfiat.org` | `rpc.testnet.postfiat.org` |
| VHS | `vhs.devnet.postfiat.org` | `vhs.testnet.postfiat.org` |
| Scoring host (SSH) | `root@<DEVNET_SCORING_HOST_IP>` | `root@<TESTNET_SCORING_HOST_IP>` |
| Cadence | Weekly (168 hours) | Weekly (168 hours) |

---

## Trigger a Scoring Round

Rounds can be triggered manually via the admin endpoint or run automatically by the built-in scheduler.

**Manual trigger:**

```bash
# Devnet
curl -X POST https://scoring-devnet.postfiat.org/api/scoring/trigger \
  -H "X-API-Key: <DEVNET_ADMIN_API_KEY>"

# Testnet
curl -X POST https://scoring-testnet.postfiat.org/api/scoring/trigger \
  -H "X-API-Key: <TESTNET_ADMIN_API_KEY>"
```

Returns `202 Accepted` with `{"dry_run": false, "status": "started"}`. The round runs in a background thread.

**Dry run (stops after UNL selection, no VL signing or publishing):**

```bash
curl -X POST "https://scoring-devnet.postfiat.org/api/scoring/trigger?dry_run=true" \
  -H "X-API-Key: <DEVNET_ADMIN_API_KEY>"
```

---

## Watch Progress

Poll the latest round's status:

```bash
# Devnet
curl "https://scoring-devnet.postfiat.org/api/scoring/rounds?limit=1" | jq '.rounds[0].status'

# Testnet
curl "https://scoring-testnet.postfiat.org/api/scoring/rounds?limit=1" | jq '.rounds[0].status'
```

Expected progression: `COLLECTING` → `SCORED` → `SELECTED` → `VL_SIGNED` → `IPFS_PUBLISHED` → `VL_DISTRIBUTED` → `ONCHAIN_PUBLISHED` → `COMPLETE`

---

## Get Latest Round Detail

Returns the most recent round with all fields (round number, status, IPFS CID, memo tx hash, timestamps):

```bash
# Devnet
curl "https://scoring-devnet.postfiat.org/api/scoring/rounds?limit=1" | jq '.rounds[0]'

# Testnet
curl "https://scoring-testnet.postfiat.org/api/scoring/rounds?limit=1" | jq '.rounds[0]'
```

---

## Inspect Results

Replace `<N>` with the round number from the latest round detail.

**Round detail:**

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N> | jq

# Testnet
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N> | jq
```

**Current UNL (from the last successful round):**

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/api/scoring/unl/current | jq

# Testnet
curl https://scoring-testnet.postfiat.org/api/scoring/unl/current | jq
```

**Signed Validator List:**

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/vl.json | jq

# Testnet
curl https://scoring-testnet.postfiat.org/vl.json | jq
```

---

## Audit Trail Files

Each completed round's full evidence chain is available via HTTPS fallback. Replace `<N>` with the round number.

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N>/metadata.json | jq
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N>/snapshot.json | jq
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N>/scores.json | jq
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N>/unl.json | jq

# Testnet
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N>/metadata.json | jq
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N>/scores.json | jq
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N>/snapshot.json | jq
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N>/unl.json | jq
```

---

## Verify via IPFS

The IPFS CID is in the round detail response (`ipfs_cid` field) and in the on-chain memo. The audit trail is pinned to both the primary IPFS node and Pinata for redundancy. Because `metadata.json` is part of the pinned directory, it does not self-reference the final root CID; use the round record or memo as the CID source of truth.

```
# Primary gateway
https://ipfs-testnet.postfiat.org/ipfs/<CID>

# Pinata public gateway
https://gateway.pinata.cloud/ipfs/<CID>
```

To fetch a specific file from the pinned directory:

```
https://ipfs-testnet.postfiat.org/ipfs/<CID>/scores.json
https://gateway.pinata.cloud/ipfs/<CID>/metadata.json
```

---

## Verify On-Chain Memo

The memo transaction hash is in the round detail response (`memo_tx_hash` field). Look it up via RPC:

```bash
# Devnet
curl -X POST https://rpc.devnet.postfiat.org \
  -d '{"method":"tx","params":[{"transaction":"<TX_HASH>"}]}' | jq '.result.Memos'

# Testnet
curl -X POST https://rpc.testnet.postfiat.org \
  -d '{"method":"tx","params":[{"transaction":"<TX_HASH>"}]}' | jq '.result.Memos'
```

The memo data (hex-decoded) contains `{"ipfs_cid":"<CID>","type":"pf_dynamic_unl","vl_sequence":<N>}`.

---

## Tail Live Logs

Stream the scoring service container logs during a round for real-time progress and error visibility:

```bash
# Devnet
ssh root@<DEVNET_SCORING_HOST_IP> "docker logs -f dynamic-unl-scoring-scoring-1"

# Testnet
ssh root@<TESTNET_SCORING_HOST_IP> "docker logs -f dynamic-unl-scoring-scoring-1"
```

---

## Diagnose Failed Rounds

If a round shows `status: FAILED`, check the error message:

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/api/scoring/rounds/<N> | jq '.error_message'

# Testnet
curl https://scoring-testnet.postfiat.org/api/scoring/rounds/<N> | jq '.error_message'
```

For more detail, check the container logs:

```bash
# Devnet
ssh root@<DEVNET_SCORING_HOST_IP> "docker logs dynamic-unl-scoring-scoring-1 2>&1 | tail -80"

# Testnet
ssh root@<TESTNET_SCORING_HOST_IP> "docker logs dynamic-unl-scoring-scoring-1 2>&1 | tail -80"
```

Common failure points:
- **Modal cold start timeout** — the LLM endpoint takes ~2-3 minutes to cold-start if idle for 20+ minutes. The scoring request has a 35-minute timeout, so this should resolve on its own. If it doesn't, check Modal dashboard.
- **IPFS pin failure** — check IPFS credentials and node reachability.
- **GitHub Pages push failure** — the `VL_DISTRIBUTED` stage retries transient 5xx and rate limits with exponential backoff. Persistent failure points: expired or revoked `GITHUB_PAGES_TOKEN`, SHA conflict with a concurrent commit to the repo, or 4xx from invalid repo/branch/path configuration. Check the service logs for the Contents API response body, then verify the PAT is current under the `postfiat-scoring-bot` account's fine-grained token list. The round fails before the on-chain memo is submitted, so no transaction is spent on a failed Pages publish.
- **On-chain memo failure** — check wallet balance (`server_info` on the RPC node) and memo destination account reserve (needs 10+ PFT).
- **VHS returns no data** — check VHS crawler is running: `ssh root@<VHS_HOST> "docker logs vhs-crawler 2>&1 | tail -20"`.

Failures before `VL_SIGNED` do not consume VL sequence numbers. Failures after `VL_SIGNED` may already have confirmed a sequence number, even if later GitHub Pages or on-chain publication fails.

---

## Operational Notes

**Modal cold start:** The LLM runs on Modal serverless with a 20-minute scaledown window. The first round after idle takes ~2-3 minutes for model weights to load. Subsequent rounds within the window complete in ~15-30 seconds.

**Scoring cadence:** The built-in scheduler checks every 5 minutes whether the configured cadence (default: 168 hours = weekly) has elapsed since the last normal scoring attempt. Normal attempts include successful and failed full scoring rounds; dry-runs and admin override rounds do not delay the normal scoring cadence. The first check happens 5 minutes after service startup.

**Round numbers vs VL sequence numbers:** Round numbers increment on every attempt (including failures). A round's `vl_sequence` field is `null` until the `VL_SIGNED` stage completes. If a round fails before `VL_SIGNED`, the reserved sequence is released. If a round fails after `VL_SIGNED`, the sequence may already be confirmed.

**Health check:**

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/health

# Testnet
curl https://scoring-testnet.postfiat.org/health
```

Returns `{"status":"ok"}` when the service is running and the database is connected.

---

## Emergency Operations

The scoring service exposes two admin-guarded override endpoints that publish a signed VL without running the automated pipeline. They are for foundation use only through Phase 1 and Phase 2, and are removed at the Phase 3 boundary when the foundation is no longer the sole publisher. Every invocation writes a full IPFS audit trail with `override: true` and the operator-supplied `reason`, and the on-chain memo uses the distinct type `pf_dynamic_unl_override`.

Both endpoints reuse the `X-API-Key: <ADMIN_API_KEY>` auth header, respect the same PostgreSQL advisory lock as the automated scheduler (so overrides never race a scheduled round), and consume the next VL sequence from the `vl_sequence` reserve/confirm/release path.

### Emergency republish with an explicit UNL

Use this when the automated scoring output is unusable or when the first-round seed / parity transition requires a specific validator set.

```bash
# Devnet example — republish the current 4-validator foundation set
curl -X POST https://scoring-devnet.postfiat.org/api/scoring/admin/publish-unl/custom \
  -H "X-API-Key: <DEVNET_ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "master_keys": [
      "nHUDXa2bH68Zm5Fmg2WaDSeyEYbiqzMLXussLMyK3t6bTCNiHKY2",
      "nHBgo2xSUVPy4zsWb1NM7CYmyYeobx7Swa3gFgoB55ipuyJwRdKX",
      "nHBg5iGpnvmbckhEUkY1oTnNqr8RbzRwKyW8x5NoGJYPVT4iS7um",
      "nHBXSCTwVUbvZg5EAZsXXTtads2ZVd8UwLsuniGcLBgH9pP8EeBc"
    ],
    "reason": "Devnet parity transition — seed VL matching the static UNL",
    "effective_lookahead_hours": 0
  }'
```

Returns `202 Accepted` with the synthetic round number. Poll the rounds endpoint to confirm the seven-stage pipeline completed:

```bash
curl "https://scoring-devnet.postfiat.org/api/scoring/rounds?limit=1" | jq '.rounds[0] | {round_number, status, override_type, override_reason, vl_sequence, ipfs_cid, memo_tx_hash}'
```

The response should show `override_type: "custom"` and a populated `ipfs_cid` and `memo_tx_hash`.

### Rollback to a historical round

Use this when a recently-published automated round must be superseded by the known-good UNL from a previous completed round. Because the VL sequence is monotonically increasing, the rollback blob is issued with the next sequence number (not the historical round's sequence). Validators accept it because it is strictly newer.

```bash
# Rollback the current testnet UNL to whatever was published in round 41
curl -X POST https://scoring-testnet.postfiat.org/api/scoring/admin/publish-unl/from-round/41 \
  -H "X-API-Key: <TESTNET_ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Rolling back round 43 — anomalous LLM reasoning on validator nHxyz",
    "effective_lookahead_hours": 1
  }'
```

For fast rollback of a blob that is still pending (lookahead has not yet elapsed on the offending round), use `effective_lookahead_hours: 0` in the request so the rollback activates immediately rather than waiting for the default 1-hour lookahead.

### Choosing the lookahead parameter

| Scenario | `effective_lookahead_hours` |
|---|---|
| Automated weekly round | 1 (default) |
| Devnet parity-transition seed VL (static UNL → URL mechanism) | 0 |
| First testnet live round (extended human-review window) | 24 |
| Rollback of a round whose activation window has already passed | 1 |
| Rollback of a round that is still pending (supersede before activation) | 0 |

### Dry-run exercise (required before declaring Phase 1 complete)

Both endpoints must be invoked at least once against a non-production-impacting target before Phase 1 is declared complete. The payloads below are safe on devnet: the custom endpoint republishes the current UNL unchanged, and the rollback endpoint replays the previous completed round.

```bash
# Look up the current UNL and an earlier completed round to target
curl -s https://scoring-devnet.postfiat.org/api/scoring/unl/current | jq
curl -s "https://scoring-devnet.postfiat.org/api/scoring/rounds?limit=5" | jq '.rounds[] | {round_number, status}'

# Invoke both endpoints with the values gathered above, then confirm
# override_type, IPFS CID, and memo transaction via the round detail query
```

---

## GitHub Pages PAT Rotation

The `VL_DISTRIBUTED` stage authenticates to the GitHub Contents API with a fine-grained PAT issued under the `postfiat-scoring-bot` service account. The PAT has a maximum lifetime of one year and must be rotated before expiration. Failure to rotate will cause every scoring round to fail at the `VL_DISTRIBUTED` stage once the token expires.

**Rotation checklist (perform ~60 days before current expiration):**

1. Log in as `postfiat-scoring-bot` on GitHub. Generate a new fine-grained PAT. Repository access: **only** `postfiatorg/postfiatorg.github.io`. Repository permissions: `Contents: Read and write`. Expiration: 1 year.
2. Update the scoring service's deployment secrets:
   - Replace `DEVNET_GITHUB_PAGES_TOKEN` in the `deploy-devnet.yml` workflow's secrets.
   - Replace `TESTNET_GITHUB_PAGES_TOKEN` in the `deploy-testnet.yml` workflow's secrets.
3. Trigger both deploy workflows to redeploy the scoring service with the new token.
4. Trigger a manual scoring round in dry-run mode on each environment to verify the new token authenticates successfully against the Contents API. A successful `VL_DISTRIBUTED` stage in the round detail response confirms rotation.
5. Revoke the old PAT from the `postfiat-scoring-bot` token list.
6. Update the calendar reminder to ~60 days before the new expiration.

If a rotation is missed and the token expires, rounds fail at `VL_DISTRIBUTED`. Rotate the PAT, redeploy, and use the admin override endpoint to republish the current UNL manually (the override path goes through the same `VL_DISTRIBUTED` stage with the new credentials).

---

## Publisher Key Rotation (Skeleton)

A full rotation procedure will be detailed before Phase 2. This section captures the invariants that any future rotation must respect.

Postfiatd rejects blobs signed by a publisher key that is not in the validator's `[validator_list_keys]` configuration. The rejection is silent (no loud error) — the validator simply continues trusting whichever prior VL it has cached until that VL's `validUntil` elapses, at which point consensus halts (see expired-list recovery below). For this reason, a key rotation is operationally hazardous on any network with validators the foundation does not control (testnet onward).

The only safe rotation pattern is the multi-publisher overlap:

1. Generate a new publisher key pair via `validator-keys create_keys` + `validator-keys create_token`. Load the new token into the scoring service's secret store alongside the existing one.
2. Announce the rotation to community validator operators with a coordinated window of at least 2 weeks.
3. Ship a postfiatd config update that adds the new publisher master key to `[validator_list_keys]` alongside the existing key. During the overlap, `[validator_list_threshold]` remains at 0 (auto-computed: 1 when there are <3 keys), so a blob from either publisher is accepted.
4. For the duration of the overlap window, the scoring service signs each VL twice — one blob with each publisher — and emits both in the same `blobs_v2` array. This ensures a validator with either key configured accepts the VL.
5. After the overlap window and confirmation that every cooperating validator has picked up the new key, ship a second postfiatd config update that removes the old publisher master key. The scoring service switches to single-publisher signing with the new key.
6. Retire the old publisher key material from the secret store.

Skip any step and you create a silent-rejection failure mode that cannot be diagnosed from a validator's logs without explicit search.

---

## Recover From an Expired VL

If the scoring service's publication path is offline long enough for the current VL's `validUntil` to pass on a validator, that validator invokes `setUNLBlocked()` and halts consensus, serving `warnRPC_EXPIRED_VALIDATOR_LIST` on RPC responses. Postfiatd does not silently fall back to the local `[validators]` block — the local list is additive into `keyListings_` and trust requires the list threshold to be met.

The default `VL_EXPIRATION_DAYS` is 500, which gives a very large margin. An expiration is therefore either the result of deliberately shortening the window or a sustained service outage.

**Diagnose:**

```bash
# Check whether any RPC node is serving the expired-VL warning
curl -X POST https://rpc.testnet.postfiat.org \
  -d '{"method":"server_info"}' | jq '.result.info.warnings // empty'
```

A `warning: "This server needs to update its list of trusted validators"` entry confirms the expiration. Check the latest VL's `expiration` field via `/vl.json` to identify when it lapsed.

**Recover:**

1. Bring the scoring service back online and confirm `/health` returns `ok`.
2. Republish a VL with the current known-good UNL via the custom admin endpoint with `effective_lookahead_hours: 0` so it activates immediately:
   ```bash
   curl -X POST https://scoring-testnet.postfiat.org/api/scoring/admin/publish-unl/custom \
     -H "X-API-Key: <TESTNET_ADMIN_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{
       "master_keys": [...current-UNL...],
       "reason": "Recovery from expired VL",
       "effective_lookahead_hours": 0,
       "expiration_days": 500
     }'
   ```
3. Within the validators' next 5-minute poll interval, the new blob is fetched, accepted, and activated. Consensus resumes.

**Prevent:** keep `VL_EXPIRATION_DAYS` at the default 500, monitor the scoring service's scheduler, and ensure the weekly round publishes a fresh blob with a rolling expiration.
