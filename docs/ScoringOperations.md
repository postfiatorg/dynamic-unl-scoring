# Scoring Service Operations Guide

Operations reference for the Dynamic UNL Scoring service on devnet and testnet.

## How the Pipeline Works

The scoring service evaluates PFT Ledger validators and publishes a signed Validator List (VL) that determines which validators are trusted for consensus. A single scoring round progresses through seven stages:

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
│         │ metadata.json (CID, hashes, gateways)                    │
│         ▼                                                          │
│  ┌──────────────┐   1-drop Payment   ┌────────────────┐            │
│  │  6. ON-CHAIN │── + memo ─────────►│  PFT Ledger    │            │
│  └──────┬───────┘                    └────────────────┘            │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────┐                                                  │
│  │  7. COMPLETE │── round finalized, all artifacts persisted       │
│  └──────────────┘                                                  │
│                                                                    │
│  Any stage failure → round marked FAILED, VL sequence released     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Each stage produces artifacts that are persisted in PostgreSQL and served via public API endpoints. If any stage fails, the round is marked `FAILED` and the VL sequence number is released for reuse.

**Artifacts per round:**

| File | Contents |
|---|---|
| `snapshot.json` | Input to the LLM: validator data with IP, ASN, geolocation, agreement scores |
| `scores.json` | Output from the LLM: overall + 5 dimension scores, per-validator reasoning, network summary |
| `unl.json` | Selected UNL validators + alternates |
| `vl.json` | Signed Validator List (v2 format, served at `/vl.json`) |
| `metadata.json` | Round metadata: IPFS CID, file hashes, gateway URLs, DB-IP attribution |

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

Expected progression: `COLLECTING` → `SCORED` → `SELECTED` → `VL_SIGNED` → `IPFS_PUBLISHED` → `ONCHAIN_PUBLISHED` → `COMPLETE`

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
curl https://scoring-devnet.postfiat.org/rounds/<N>/metadata.json | jq
curl https://scoring-devnet.postfiat.org/rounds/<N>/snapshot.json | jq
curl https://scoring-devnet.postfiat.org/rounds/<N>/scores.json | jq
curl https://scoring-devnet.postfiat.org/rounds/<N>/unl.json | jq

# Testnet
curl https://scoring-testnet.postfiat.org/rounds/<N>/metadata.json | jq
curl https://scoring-testnet.postfiat.org/rounds/<N>/scores.json | jq
curl https://scoring-testnet.postfiat.org/rounds/<N>/snapshot.json | jq
curl https://scoring-testnet.postfiat.org/rounds/<N>/unl.json | jq
```

---

## Verify via IPFS

The IPFS CID is in the round detail response (`ipfs_cid` field) or in `metadata.json`. The audit trail is pinned to both the primary IPFS node and Pinata for redundancy.

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
- **On-chain memo failure** — check wallet balance (`server_info` on the RPC node) and memo destination account reserve (needs 10+ PFT).
- **VHS returns no data** — check VHS crawler is running: `ssh root@<VHS_HOST> "docker logs vhs-crawler 2>&1 | tail -20"`.

Failed rounds do not consume VL sequence numbers — the sequence is reserved before signing and released on failure.

---

## Operational Notes

**Modal cold start:** The LLM runs on Modal serverless with a 20-minute scaledown window. The first round after idle takes ~2-3 minutes for model weights to load. Subsequent rounds within the window complete in ~15-30 seconds.

**Scoring cadence:** The built-in scheduler checks hourly whether the configured cadence (default: 168 hours = weekly) has elapsed since the last successful round. The first check happens 5 minutes after service startup.

**Round numbers vs VL sequence numbers:** Round numbers increment on every attempt (including failures). VL sequence numbers only increment on successful rounds (they use a reserve/confirm/release pattern). A round's `vl_sequence` field is `null` until the `VL_SIGNED` stage completes. After multiple failed attempts, the round number may be much higher than the VL sequence.

**Health check:**

```bash
# Devnet
curl https://scoring-devnet.postfiat.org/health

# Testnet
curl https://scoring-testnet.postfiat.org/health
```

Returns `{"status":"ok"}` when the service is running and the database is connected.
