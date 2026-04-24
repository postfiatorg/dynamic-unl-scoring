# Dynamic UNL: Implementation Milestones

Updated after Phase 0 completion (2026-03-13). Original plan lives in `postfiatd/docs/dynamic-unl/ImplementationPlan.md`. This version reflects what actually happened and adjusts the remaining phases accordingly.

**Difficulty scale:** ★☆☆☆☆ Trivial | ★★☆☆☆ Easy | ★★★☆☆ Medium | ★★★★☆ Hard | ★★★★★ Very Hard

**Time estimates** assume a solo developer with heavy LLM-assisted development (Claude Code, Codex).

**Reference design:** All architectural decisions, trust models, and protocol details are defined in [Design.md](Design.md). This document covers *how* and *when* to build it, not *what* to build.

---

## Overview

| Phase | Description | Milestones | Complete | Progress |
|-------|-------------|-----------|----------|----------|
| **Phase 0** | Research & Validation | 4 | 4 | `████████████████████` 100% |
| **Phase 1** | Foundation Scoring Pipeline | 13 | 9 | `█████████████░░░░░░░` 69% |
| **Phase 2** | Validator Verification (GPU Sidecars) | 9 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Phase 3** | Authority Transfer & Proof-of-Logits | 6 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Total** | | **32** | **13** | `████████░░░░░░░░░░░░` **41%** |

---

## Changes from Original Plan

Phase 0 and the first devnet scoring round revealed several constraints not anticipated in the original plan. The core design is unchanged — only the model, infrastructure, and a handful of VL publication details differ.

| Area | Original Plan | Actual Outcome | Why |
|---|---|---|---|
| **Model** | 7B-32B (e.g. Qwen 2.5-32B) | Qwen3-Next-80B-A3B-Instruct-FP8 (80B MoE, 3B active) | Two benchmark rounds tested 7 models. Smaller models lacked scoring quality. 80B MoE fits on single H200 at ~75 GB with FP8. |
| **GPU platform** | RunPod serverless | Modal serverless | RunPod's SGLang is broken (9 attempts, community confirmed). RunPod also doesn't recognize the Qwen3-Next architecture. |
| **GPU type** | A40/L4/A100 (consumer-accessible) | H200 (141 GB) | Model requires ~75 GB VRAM + 36 GB Mamba cache. Only H200+ has enough headroom for single-GPU deterministic inference. |
| **Quantization** | GPTQ-Int4 or AWQ | FP8 (native) | GPTQ/AWQ trigger Marlin repacking OOM on large MoE models. FP8 avoids repacking entirely. |
| **Determinism** | Research + harness design only | 100% confirmed empirically | 5 full scoring runs produced bit-identical output. Exceeds the >99% target for Phase 2 entry. |
| **Milestone 0.4 (Geolocation)** | MaxMind + ASN setup | Complete — pyasn for ASN, DB-IP Lite for country-level geolocation | ASN data is public/publishable (IPFS). Geolocation uses DB-IP Lite (CC BY 4.0, freely publishable). MaxMind dropped from the scoring pipeline — its EULA prohibits republishing derived data, which conflicts with IPFS audit trail publication and Phase 2 reproducibility (validators would each need a MaxMind license). |
| **VL `effective` timestamp lookahead** | Not specified; generator initially omitted the optional `effective` field, causing immediate activation on fetch | Adopted as a first-class mechanism in M1.10.6 with parameterized lookahead (0 for parity, 1 h for automated rounds, 24 h for first testnet live round, caller-specified for admin overrides) | Without lookahead, validators transition UNLs at slightly different wall-clock times based on their independent 5-minute HTTP poll cycles, creating a fork-risk propagation window. `ValidatorList.cpp:1406-1448` and `:1946-2003` already implement the pending-blob rotation; we just need to use it. Collapses the propagation window to sub-second consensus precision. |
| **Testnet VL transition mechanism** | Original plan anticipated shipping a postfiatd release with a new publisher key and URL, with a waiting window for community validators to upgrade | Publisher-key continuity: the scoring service reuses the existing `ED3F1E…` master key; the transition is a content overwrite at the existing `postfiat.org/testnet_vl.json` URL; no community validator configuration change is required | Minimises community operator friction and eliminates the silent-rejection failure mode that a key rotation would have created. Postfiatd's unknown-publisher-key behavior (untrusted rejection with no loud error) makes non-coordinated key changes operationally hazardous on a ~40-validator network. |
| **Admin override endpoints** | Not in the original plan | Added as M1.11 — two admin-guarded endpoints on the scoring service (`publish-unl/custom`, `publish-unl/from-round/{round_id}`) | Provides an auditable kill-switch path for Phase 1 and Phase 2 where the foundation's UNL is authoritative. Scheduled for removal at the Phase 3 boundary when validators produce the UNL via commit-reveal. |
| **VL distribution to `postfiat.org`** | Original plan assumed the scoring service's own `/vl.json` endpoint (at `scoring-{env}.postfiat.org/vl.json`) would be the authoritative source validators point at | Validators continue to read from the existing `postfiat.org/testnet_vl.json` (and a new `postfiat.org/devnet_vl.json`), both served by GitHub Pages from `postfiatorg/postfiatorg.github.io`. The scoring service pushes each round's signed VL into that repository via the GitHub Contents API, in a new orchestrator stage `VL_DISTRIBUTED` (M1.10.7) between `IPFS_PUBLISHED` and `ONCHAIN_PUBLISHED` | Preserves the existing URL every testnet community validator already trusts, avoids any operator configuration change, and mirrors the proxy-free publication pattern across devnet and testnet. The scoring-native endpoint `scoring-{env}.postfiat.org/vl.json` remains available for tooling and debugging, but is no longer the source validators consume. |

---

## Overview

```
Phase 0                Phase 1                  Phase 2                    Phase 3
Research &             Foundation               Validator                  Full Verification
Validation             Scoring                  Verification               Proof of Logits

~1 week                ~4-6 weeks               ~6-8 weeks                 ~5-7 weeks

┌────────────┐    ┌──────────────────┐    ┌────────────────────┐    ┌──────────────────┐
│Model select│    │Data collection   │    │Commit-reveal proto │    │Logit commitment  │
│GPU setup   │───►│LLM scoring       │───►│GPU sidecar         │───►│Spot-check tools  │
│Determinism │    │VL generation     │    │Convergence monitor │    │Authority transfer│
│research    │    │IPFS + on-chain   │    │Validator onboarding│    │Identity portal   │
│            │    │Deploy + test     │    │Deploy + test       │    │Full system test  │
└────────────┘    └──────────────────┘    └────────────────────┘    └──────────────────┘
      │                   │                        │                        │
      ▼                   ▼                        ▼                        ▼
  Decision Gate:      Decision Gate:           Decision Gate:          Dynamic UNL
  Go/No-Go on        Phase 1 stable           Convergence             fully operational,
  local inference     on testnet               proven                  foundation replaced
```

**Total estimated time:** ~17-23 weeks (4-5.5 months)

---

## Repositories

| Repository | Language | Purpose | Created In |
|---|---|---|---|
| `postfiatd` (existing) | C++ | Node-side changes: memo watching, VL fetching, amendment (Phase 2+) | — |
| `dynamic-unl-scoring` (new) | Python (FastAPI) | Scoring pipeline: data collection, LLM inference, VL generation, IPFS, on-chain | Phase 1 |
| `validator-scoring-sidecar` (new) | Python | GPU sidecar: model loading, inference, commit-reveal, logit capture | Phase 2 |

---

## Infrastructure

### Instances (Vultr)

```
┌────────────────────────────────────────────────────────────────────┐
│                         DEVNET ENVIRONMENT                         │
│                                                                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ Validator 1 │ │ Validator 2 │ │ Validator 3 │ │ Validator 4 │   │
│  │  (existing) │ │  (existing) │ │  (existing) │ │  (existing) │   │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │
│                                                                    │
│  ┌─────────────┐ ┌─────────────┐                                   │
│  │   RPC Node  │ │     VHS     │                                   │
│  │  (existing) │ │  (existing) │                                   │
│  └─────────────┘ └─────────────┘                                   │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Scoring Service (NEW)                                       │  │
│  │  Vultr Cloud Compute Regular                                 │  │
│  │  2 vCPU | 4 GB RAM | 80 GB SSD                               │  │
│  │  Ubuntu 24.04 LTS | ~$18/month                               │  │
│  │  Runs: dynamic-unl-scoring (FastAPI)                         │  │
│  │  Connects to: VHS, IPFS, PFTL RPC, Modal                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                        TESTNET ENVIRONMENT                         │
│                                                                    │
│  ┌─────────────┐ ┌─────────────┐           ┌─────────────┐         │
│  │ Foundation  │ │  External   │    ...    │  External   │         │
│  │ Validators  │ │ Validator 1 │           │ Validator N │         │
│  │  (5, ours)  │ │ (~25 total) │           │             │         │
│  └─────────────┘ └─────────────┘           └─────────────┘         │
│                                                                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                   │
│  │   RPC Node  │ │     VHS     │ │  IPFS Node  │                   │
│  │  (existing) │ │  (existing) │ │  (existing) │                   │
│  └─────────────┘ └─────────────┘ └─────────────┘                   │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Scoring Service (NEW)                                       │  │
│  │  Vultr Cloud Compute Regular                                 │  │
│  │  2 vCPU | 4 GB RAM | 80 GB SSD                               │  │
│  │  Ubuntu 24.04 LTS | ~$18/month                               │  │
│  │  Runs: dynamic-unl-scoring (FastAPI)                         │  │
│  │  Connects to: VHS, IPFS, PFTL RPC, Modal                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    SHARED (BOTH ENVIRONMENTS)                      │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Modal Serverless Endpoint                                    │  │
│  │  Model: Qwen3-Next-80B-A3B-Instruct-FP8                     │  │
│  │  Backend: SGLang v0.5.6, deterministic inference             │  │
│  │  GPU: H200 (141 GB), single GPU (TP=1)                      │  │
│  │  Pay-per-use: $4.54/hr active | $0 idle (scale to zero)     │  │
│  │  Estimated monthly: ~$2-8 (weekly scoring, both envs)        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  IPFS Node (existing)                                        │  │
│  │  https://ipfs-testnet.postfiat.org/ipfs/                     │  │
│  │  Shared by devnet + testnet (content-addressed, no conflict) │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### Scoring Service Instance Setup (Vultr)

Step-by-step for provisioning each scoring service instance:

1. **Create instance** on Vultr: Cloud Compute → Regular Performance → 2 vCPU / 4 GB / 80 GB SSD → Ubuntu 24.04 → same region as other infra
2. **DNS**: Point `scoring-devnet.postfiat.org` and `scoring-testnet.postfiat.org` to their IPs
3. **Initial setup**: SSH in, install Docker + Docker Compose, install Caddy (reverse proxy + auto HTTPS)
4. **Deploy**: Docker Compose with the `dynamic-unl-scoring` service + PostgreSQL
5. **Environment variables**: PFTL RPC URL, wallet secret, VHS URL, IPFS credentials, Modal token, IPFS gateway URL
6. **Caddy config**: Reverse proxy to the FastAPI service on port 8000, auto-TLS via Let's Encrypt
7. **Monitoring**: Basic health check endpoint, log rotation, optional uptime monitoring

### Modal Serverless Setup

Deployment script: `infra/deploy_endpoint.py`. See `phase0/docs/DeployQwen80B.md` for full details.

```bash
modal deploy infra/deploy_endpoint.py   # ~3s (cached image), ~18 min (first build)
```

Configuration is in the deployment script via environment variable defaults. Key settings: FP8 quantization, `--mem-fraction-static 0.75`, `--chunked-prefill-size 4096`, `--enable-deterministic-inference`, DeepGEMM pre-compiled in image.

### Monthly Cost Summary

| Item | Devnet | Testnet | Total |
|---|---|---|---|
| Scoring Service (Vultr) | ~$18 | ~$18 | $36 |
| Modal Serverless (shared) | — | — | ~$2-8 |
| IPFS (existing) | $0 | $0 | $0 |
| VHS (existing) | $0 | $0 | $0 |
| DB-IP Lite (geolocation) | $0 | $0 | $0 |
| **Total new monthly cost** | | | **~$38-44** |

---

## Phase 0: Research & Validation

**Duration:** ~1 week | **Difficulty:** ★★★☆☆ Medium

**Goal:** Validate that the phased design is feasible before writing production code. Select the model, set up GPU infrastructure, document determinism research for Phase 2+.

```
Milestone 0.1          Milestone 0.2          Milestone 0.3         Milestone 0.4
Model Selection        Modal Setup            Determinism           Geolocation
& Benchmarking         & Testing              Research              & ASN Setup

~2-3 days              ~1-2 days              ~2 days               ~2 hours
★★★☆☆                 ★★☆☆☆                 ★★★★☆                ★☆☆☆☆
      │                      │                      │                    │
      └──────────┬───────────┘                      │                    │
                 │                                  │                    │
                 ▼                                  │                    │
         Decision Gate ◄────────────────────────────┘                    │
         Go/No-Go on                                                     │
         local inference ◄───────────────────────────────────────────────┘
```

---

### Milestone 0.1: Model Selection & Benchmarking

**Duration:** ~2-3 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** None

**Goal:** Select an open-weight model that produces validator scoring quality comparable to the current approach. This is a collaborative effort — leveraging deep knowledge of open-source LLMs to quickly narrow down candidates.

**Steps:**

**0.1.1 — Define scoring benchmark** ✅ (0.5 day)
- Create a benchmark dataset: take real validator data from VHS (anonymized if needed) for 15-30 validators
- Define evaluation criteria: score consistency (same input → similar scores across runs), reasoning quality (does the model explain its scores coherently), score differentiation (does it distinguish good from bad validators meaningfully)
- Write the scoring prompt based on the design spec: all validator data packets in a single prompt, structured JSON output with score (0-100) + reasoning per validator

**0.1.2 — Select candidate models** ✅ (collaborative, 0.5-1 day)
- Target model class: 7B-32B parameters (fits on a single GPU, Modal serverless compatible)
- Candidate families to evaluate:
  - Qwen 2.5/3.x (32B, 14B, 7B)
  - Llama 4 Scout / Llama 3.x (70B if budget allows, 8B for baseline)
  - DeepSeek V3/R1 distilled variants
  - Mistral/Mixtral (if applicable)
- For each candidate: note parameter count, quantization options (FP16, BF16, INT8), VRAM requirements, Modal serverless compatibility
- Use safetensors format with HuggingFace snapshot revision pinning (not GGUF)

**0.1.3 — Run benchmark across candidates** ✅ (1 day)
- For each candidate model:
  - Deploy temporarily on Modal serverless (or use HuggingFace Inference API for quick tests)
  - Run the scoring prompt 5 times with the benchmark dataset
  - Record: scores, reasoning, JSON format compliance, latency, cost per run
  - Test with temperature 0 / greedy decoding
- Compare results across models and across runs of the same model

**0.1.4 — Select and document final model** ✅ (0.5 day)
- Choose the model based on: scoring quality, consistency, cost, Modal availability
- Document the selection with rationale
- Record: exact model ID, quantization, VRAM requirement, expected Modal GPU type, per-run cost estimate
- Define the full **execution manifest** — hash and record:
  - HuggingFace snapshot revision and all weight shard hashes (safetensors)
  - Tokenizer files and config files
  - Prompt template version
  - Inference engine (SGLang) version and configuration
  - Attention backend, dtype, quantization mode
  - Container image digest
  - CUDA / driver version
- Construct raw prompt strings directly (do not rely on chat-template defaults — upstream changes are a silent divergence risk)

**Deliverables:**
- Benchmark dataset (JSON file with validator profiles)
- Benchmark results comparison document
- Final model selection with rationale
- Full execution manifest definition (all convergence-critical parameters)
- Model configuration (ID, quantization, GPU type, cost)

---

### Milestone 0.2: Modal Setup & Testing

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestone 0.1 (model selected)

**Goal:** Set up the Modal serverless endpoint with the selected model and verify it works end-to-end.

**Steps:**

**0.2.1 — Create Modal account and billing** ✅ (1 hour)
- Sign up at modal.com
- Add payment method
- Note: Modal charges per second of active GPU time, no charge when idle

**0.2.2 — Deploy serverless endpoint** ✅ (2-4 hours)
- Deploy via `modal deploy infra/deploy_endpoint.py`
- Configure: SGLang backend, FP8 quantization, `--enable-deterministic-inference`
- Key settings: `--mem-fraction-static 0.75`, `--chunked-prefill-size 4096`, DeepGEMM pre-compiled
- Deploy and wait for the endpoint to become active

**0.2.3 — Test the endpoint** ✅ (2-4 hours)
- Test with curl against the OpenAI-compatible API:
  ```bash
  curl -X POST "<MODAL_ENDPOINT_URL>/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model": "<model_id>", "messages": [{"role": "user", "content": "<scoring prompt>"}], "max_tokens": 4096, "temperature": 0}'
  ```
- Verify: response format (JSON), scoring output structure, latency, cold start time
- Test cold start: wait for endpoint to scale down, send request, measure time to first response
- Test with the full benchmark prompt (all validator profiles)

**0.2.4 — Document endpoint configuration** ✅ (1-2 hours)
- Record endpoint URL (store securely)
- Document cold start behavior and expected latency
- Note any configuration adjustments needed

**Deliverables:**
- Active Modal serverless endpoint
- Endpoint URL (stored securely)
- Test results document with latency measurements

---

### Milestone 0.3: Determinism Research & Reproducibility Harness Design

**Duration:** ~3 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestone 0.1 (model selected)

**Goal:** Document determinism research, design the reproducibility harness, and identify candidate GPU types. The harness itself will be built and run during Phase 1 — its results are a hard gate for Phase 2 entry.

**Note:** This does not block Phase 1. Phase 1 runs fine without determinism — only the foundation scores. This is preparation for Phase 2+ where multiple validators must produce identical outputs.

**Steps:**

**0.3.1 — Survey deterministic inference solutions** ✅ (1 day)
- Research and document current state of SGLang deterministic mode (`--enable-deterministic-inference`): how it works, what it guarantees, performance overhead (~34%), which attention backends supported (FlashInfer, FA3, Triton), which models/GPUs validated
- Document alternative solutions for reference: Ingonyama deterministic kernels, LayerCast
- Document compatibility with the selected model, GPU requirements, known limitations

**0.3.2 — Document the mandatory GPU type decision** ✅ (0.5 day)
- Based on the selected model and SGLang deterministic mode, identify candidate mandatory GPU types
- Consider: availability on Modal, cost, community accessibility
- Candidates likely: NVIDIA A40, L4, RTX 4090 (consumer), A100 40GB
- Document trade-offs (cost vs availability vs determinism guarantees)
- The final GPU choice will be made after empirical testing via the reproducibility harness

**0.3.3 — Design the reproducibility harness** ✅ (1.5 days)
- Define the harness that will run during Phase 1 and gate Phase 2 entry:
  - **What to measure:**
    - Output-text equality rate (same input → same output text?)
    - Score equality rate (same input → same validator scores?)
    - Token-level transcript equality rate
    - Logit-hash equality rate (for Phase 3)
  - **Test matrix:**
    - Same worker, multiple runs
    - Different workers, same GPU type
    - Different datacenters
    - Warm vs cold starts
  - **Pass criteria:** >99% output equality on the mandatory GPU type
  - **Failure path:** if SGLang deterministic mode does not achieve >99%, evaluate vLLM as fallback. If neither achieves it, Phase 2 design must be revisited.
- Document the harness design, test matrix, and pass/fail criteria
- Link to [ResearchStatus.md](research/ResearchStatus.md)

**Deliverables:**
- Updated determinism research document (extends [ResearchStatus.md](research/ResearchStatus.md))
- Mandatory GPU type candidates with trade-off analysis
- Reproducibility harness design document (test matrix, measurements, pass criteria)
- Harness will be built and executed during Phase 1 (see Phase 1 Decision Gate)

---

### Milestone 0.4: Geolocation Setup & Legal Assessment

**Duration:** ~1 day | **Difficulty:** ★☆☆☆☆ Trivial | **Dependencies:** None

**Goal:** Set up data sources for validator geolocation and ISP identification. Assess licensing constraints for data publication.

**Data source split:** ISP/cloud provider identification uses public ASN data (freely publishable). Country-level geolocation uses DB-IP Lite (CC BY 4.0, freely publishable with attribution). MaxMind GeoIP2 was evaluated but its EULA prohibits republishing any derived data — including country-level lookups — which conflicts with both the IPFS audit trail (all scoring inputs must be publicly verifiable) and Phase 2 reproducibility (validators would each need their own MaxMind license to reproduce the scoring prompt). DB-IP Lite provides the same country-level accuracy with no licensing restrictions.

**Steps:**

**0.4.1 — Set up DB-IP Lite** ✅ (2 hours)
- Download the IP-to-Country Lite database from db-ip.com (MMDB format, ~24 MB, updated monthly)
- DB-IP Lite is licensed under CC BY 4.0 — freely publishable with attribution ("Geolocation by DB-IP.com")
- No account or API key required — direct download
- Test with known validator IPs, verify country accuracy
- Bake into Docker image alongside ASN data (same refresh pattern — update quarterly)

**0.4.2 — Identify ASN data source** ✅ (2 hours)
- Evaluate public ASN lookup options: Team Cymru IP-to-ASN, RIPE RIS, local pyasn database, ipinfo.io free tier
- ASN data provides: AS number, ISP name (e.g., "DigitalOcean"), organization — all publishable
- Select a source and verify it returns accurate ISP/provider data for known validator IPs
- Document the chosen source and its query method

**0.4.3 — Legal/licensing assessment** ✅ (0.5 day)
- Confirm DB-IP Lite CC BY 4.0 compliance: attribution required in published artifacts ("Geolocation by DB-IP.com" in IPFS metadata)
- Review what identity attestation data can be published on-chain (attestation status only, no PII — see Milestone 3.5)
- Document licensing constraints and rationale for the data source split

**Deliverables:**
- DB-IP Lite country database downloaded and verified (for publishable country-level geolocation)
- ASN data source selected and verified (for publishable ISP/provider data)
- Licensing assessment documented

---

### Phase 0 Decision Gate

**Criteria for proceeding to Phase 1:**

| Criterion | Required | Status |
|---|---|---|
| Open-weight model selected that produces acceptable scoring quality | Yes | Done — Qwen3-Next-80B-A3B-Instruct-FP8 |
| GPU endpoint active and tested (SGLang backend) | Yes | Done — Modal, single H200 |
| Full execution manifest defined and recorded | Yes | Done — see `phase0/docs/README.md` |
| DB-IP Lite country database downloaded and verified | Yes | Done — CC BY 4.0, freely publishable with attribution |
| Determinism research documented + reproducibility harness designed | No (but harness must run during Phase 1) | Done — 100% determinism confirmed (5 runs, bit-identical) |

**Phase 0 completed 2026-03-13.** All Phase 0 documentation is in `phase0/docs/`. See `phase0/docs/README.md` for the summary and execution manifest.

---

## Phase 1: Foundation Scoring

**Duration:** ~4-6 weeks | **Difficulty:** ★★★★☆ Hard

**Goal:** Build and deploy the foundation's automated scoring pipeline. The pipeline collects validator data, calls the LLM, generates a signed VL, publishes the audit trail to IPFS, and publishes the UNL hash on-chain. Validators consume the VL exactly as they do today — no node changes required.

```
         Milestone 1.1          Milestone 1.2
         Repo Setup             Infra Provisioning
         ~1-2 days              ~1 day
              │                      │
              └──────────┬───────────┘
                         │
                         ▼
                    M 1.3
                    postfiatd
                    Update & Release
                    ~3-4 days
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         M 1.4       M 1.5       M 1.6
         Data        LLM         VL
         Collection  Scoring     Generation
         ~3-4 days   ~4-5 days   ~3-4 days
              │          │          │
              └──────────┼──────────┘
                         ▼
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         M 1.7       M 1.8       M 1.9
         IPFS        On-Chain    Orchestrator
         Publish     Memo        & Scheduler
         ~2-3 days   ~2-3 days   ~3-4 days
              │          │          │
              └──────────┼──────────┘
                         ▼
                    M 1.10
                    Devnet
                    Testing
                    ~5-7 days
                         │
                         ▼
                    M 1.11
                    Testnet
                    Deploy
                    ~3-4 days
```

---

### Milestone 1.1: Scoring Service Repository Setup

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Phase 0 complete | **Status:** Complete

**Goal:** Add the FastAPI service skeleton alongside existing Phase 0 scripts. No existing code is moved or modified — the new service package is added alongside current scripts and benchmarks.

**Deviations from original plan:**

| Original plan | Actual | Rationale |
|---|---|---|
| `app/` package name | `scoring_service/` | More descriptive, avoids ambiguity across PostFiat repos |
| `uv` for dependency management | `pip` + `requirements.txt` | Familiar, proven, zero learning curve for this project size |
| `ruff` for linting | Deferred | Small codebase, rapid Phase 1 development. Add when codebase stabilizes. |
| `pyproject.toml` | `requirements.txt` + `requirements-docker.txt` | Simpler, familiar. pyproject.toml benefits don't apply without ruff. |
| `asyncpg` (async database) | `psycopg2` (sync) | Proven pattern from scoring-onboarding. Weekly scoring doesn't benefit from async DB. |
| `hypothesis` for property testing | Deferred | Over-engineering at this stage. Add during M1.4 scoring logic. |
| `RUNPOD_*` env vars | `MODAL_ENDPOINT_URL` | RunPod was dropped in Phase 0 in favor of Modal |

**Steps:**

**1.1.1 — Project structure** ✅ (2-4 hours)
```
dynamic-unl-scoring/
├── scoring_service/
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Pydantic settings (env vars)
│   ├── database.py                # PostgreSQL connection + migration runner
│   ├── logging.py                 # Structured logging (structlog)
│   ├── api/
│   │   ├── __init__.py            # Router aggregation
│   │   └── health.py              # Health check endpoint
│   ├── clients/                   # External system integrations (I/O)
│   │   ├── vhs.py                 # VHS API client (M1.4)
│   │   ├── crawl.py               # postfiatd /crawl IP resolution (M1.4)
│   │   ├── asn.py                 # ASN/ISP lookup via pyasn (M1.4)
│   │   ├── geoip.py               # DB-IP Lite country geolocation (M1.4)
│   │   ├── identity.py            # On-chain identity memos (M3.5)
│   │   ├── modal.py               # Modal LLM endpoint (M1.5)
│   │   └── ipfs.py                # IPFS pinning (M1.7)
│   ├── services/                  # Business logic
│   │   ├── collector.py           # Snapshot assembly from clients (M1.4)
│   │   ├── scorer.py              # LLM scoring + prompt building (M1.5)
│   │   ├── vl_generator.py        # Signed VL JSON generation (M1.6)
│   │   ├── publisher.py           # IPFS + on-chain publication (M1.7-M1.8)
│   │   └── orchestrator.py        # Pipeline state machine (M1.9)
│   └── models/                    # Pydantic data models
├── migrations/                    # PostgreSQL numbered SQL migrations
├── tests/
├── scripts/                       # Standalone CLI tools
├── phase0/                        # Phase 0 archival (benchmarks, results, docs)
├── Dockerfile
├── docker-compose.yml             # Service + PostgreSQL 16
├── requirements.txt
├── requirements-docker.txt        # Service-only deps (used by Dockerfile)
└── README.md
```

**1.1.2 — Base configuration** ✅ (2-4 hours)
- Pydantic settings class with all environment variables:
  ```
  # Database
  DATABASE_URL

  # PFTL
  PFTL_RPC_URL, PFTL_WALLET_SECRET, PFTL_MEMO_DESTINATION, PFTL_NETWORK (devnet/testnet)

  # VHS
  VHS_API_URL (e.g., https://vhs.testnet.postfiat.org)

  # Modal (LLM inference endpoint)
  MODAL_ENDPOINT_URL

  # IPFS
  IPFS_API_URL, IPFS_GATEWAY_URL

  # Scoring
  SCORING_CADENCE_HOURS (default: 168 = weekly)
  SCORING_MODEL_ID, SCORING_MODEL_NAME

  # VL Publisher
  VL_PUBLISHER_TOKEN (base64 — same token used by generate_vl.py)
  VL_OUTPUT_URL (where the signed VL is served)
  ```
- Docker Compose with FastAPI service + PostgreSQL 16
- Health check endpoint at `/health` that verifies database connectivity
- **Canonical JSON serialization** (RFC 8785 / JCS) for all artifacts that get hashed — standard JSON is non-deterministic in key ordering, whitespace, and number formatting, which causes hash divergence even when content is identical
- **Structured JSON logging** via `structlog` — compatible with existing Promtail → Loki → Grafana stack
- Optional `/metrics` endpoint (Prometheus format) for Grafana to scrape operational metrics (rounds completed, scoring latency, IPFS upload time)
- Database migration runner: numbered SQL files in `migrations/`, tracked in `schema_migrations` table (same pattern as scoring-onboarding)

**1.1.3 — CI/CD pipeline** ✅ (2-4 hours)
- GitHub Actions CI: pytest + Docker build on PRs
- Deploy workflow: Docker build + push to Docker Hub on main push. SSH deploy step added in M1.2 when Vultr instance is provisioned.

**Deliverables:**
- `scoring_service/` package with working FastAPI app and `/health` endpoint
- Docker Compose that starts the service + PostgreSQL
- CI/CD pipeline
- `env.example` with all required variables documented
- `migrations/001_init.sql` with `scoring_rounds` table
- `tests/` with passing health endpoint test

---

### Milestone 1.2: Infrastructure Provisioning

**Duration:** ~1 day | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestone 1.1 | **Status:** Complete

**Goal:** Provision Vultr instances for devnet and testnet, install Docker and Caddy, configure DNS and firewall, and set GitHub secrets. This prepares the infrastructure so instances are ready when the pipeline is built.

**Deployment architecture (set up in M1.1):**
- Environment-specific files: `.env.devnet`, `.env.testnet` (committed, non-secret values only)
- Environment-specific compose files: `docker-compose.devnet.yml`, `docker-compose.testnet.yml` (pull pre-built images, no build step)
- Environment-specific deploy workflows: `deploy-devnet.yml`, `deploy-testnet.yml` (triggered by push to `devnet`/`testnet` branch)
- Docker images tagged per environment: `agtipft/dynamic-unl-scoring:devnet-latest`, `testnet-latest`
- Secrets injected at deploy time via GitHub secrets → `.env` created on host
- Local development uses `docker-compose.yml` (builds from source, mounts volumes, `--reload`)

**Steps:**

**1.2.1 — Provision and set up instances** ✅ (2-4 hours)

For each environment (devnet and testnet):
- Vultr: Cloud Compute → Regular → 2 vCPU / 4 GB / 80 GB → Ubuntu 24.04
- Same region as the environment's validators
- SSH key access configured
- DNS: `scoring-devnet.postfiat.org` / `scoring-testnet.postfiat.org` pointing to the instance IP

Then SSH into each instance and run the one-time setup (the deploy workflow handles all subsequent deployments automatically):
  ```bash
  # Install Docker
  curl -fsSL https://get.docker.com | sh

  # Install Caddy
  apt install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt update && apt install -y caddy

  # Configure Caddy reverse proxy (use the correct hostname per environment)
  cat > /etc/caddy/Caddyfile << EOF
  scoring-devnet.postfiat.org {
      reverse_proxy localhost:8000
  }
  EOF
  systemctl restart caddy

  # Firewall
  ufw allow 22/tcp comment 'SSH'
  ufw allow 80/tcp comment 'HTTP (Caddy ACME)'
  ufw allow 443/tcp comment 'HTTPS'
  ufw --force enable

  # Create application directory
  mkdir -p /opt/dynamic-unl-scoring
  ```
- Verify Caddy is serving HTTPS: `curl https://scoring-devnet.postfiat.org` (502 Bad Gateway expected — no app deployed yet, but confirms Caddy + TLS are working)

**1.2.2 — Configure GitHub secrets** ✅ (1 hour)

Set now (M1.2):

| Secret | Value |
|--------|-------|
| `DOCKERHUB_USERNAME` | Docker Hub login |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `VULTR_SSH_USER` | SSH user (root) |
| `VULTR_SSH_KEY` | SSH private key for deployment |
| `VULTR_DEVNET_HOST` | Devnet instance IP |
| `VULTR_TESTNET_HOST` | Testnet instance IP |
| `DEVNET_DB_PASSWORD` | Devnet PostgreSQL password |
| `TESTNET_DB_PASSWORD` | Testnet PostgreSQL password |
| `MODAL_ENDPOINT_URL` | Modal LLM endpoint |
| `IPFS_API_URL` | IPFS node API URL |
| `IPFS_API_USERNAME` | IPFS API username |
| `IPFS_API_PASSWORD` | IPFS API password |
| `IPFS_GATEWAY_URL` | IPFS public gateway URL |

Set later at M1.6 (VL Generation):

| Secret | Value |
|--------|-------|
| `DEVNET_PFTL_WALLET_SECRET` | Devnet chain wallet secret |
| `DEVNET_PFTL_MEMO_DESTINATION` | Devnet memo destination address |
| `DEVNET_VL_PUBLISHER_TOKEN` | Devnet VL signing token |
| `TESTNET_PFTL_WALLET_SECRET` | Testnet chain wallet secret |
| `TESTNET_PFTL_MEMO_DESTINATION` | Testnet memo destination address |
| `TESTNET_VL_PUBLISHER_TOKEN` | Testnet VL signing token |

**Deliverables:**
- Two running Vultr instances with Docker, Caddy, and firewall configured
- DNS records resolving to the correct instance IPs
- Caddy serving HTTPS on both domains
- GitHub secrets configured (except PFTL/VL secrets, deferred to M1.6)

---

### Milestone 1.3: postfiatd Version Update & Release Automation

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.2 | **Status:** Complete

**Goal:** Update postfiatd with the `/crawl` IP exposure fix, audit upstream rippled changes since 3.0.0, and establish proper versioning and automated release infrastructure for publishing new Docker images.

**Steps:**

**1.3.1 — Expose `pubkey_validator` in `/crawl` response** ✅ (0.5 day)
- Add `pubkey_validator` directly in `OverlayImpl::getServerInfo()` after the `NetworkOPs::getServerInfo()` call, bypassing the `admin` gate
- Verify via `curl` against a local node that `/crawl` response includes `server.pubkey_validator`

**1.3.2 — Audit upstream rippled changes since 3.0.0** ✅ (1-2 days)
- Review rippled changelog and commit history from 3.0.0 to 3.1.2
- Identify changes relevant to PFT Ledger: consensus fixes, security patches, protocol improvements, performance gains
- Decide which changes to include in the next postfiatd release — document rationale for each inclusion/exclusion
- Merge selected changes via `git merge 3.1.2`, resolve any conflicts with PostFiat-specific code (account exclusion, Orchard/Halo2)

**1.3.3 — Versioning and release automation** ✅ (1-2 days)
- Version sourced from `BuildInfo.cpp` — every build produces `{network}-{size}-latest` (rolling) and `{network}-{size}-{version}` (immutable)
- Overwrite protection: workflow queries Docker Hub API before building, fails if versioned tag already exists
- `deploy.yml` and `update.yml` accept optional `version` parameter for targeted deployments and rollbacks
- Feature builds exempt via `image_tag` input (skip version extraction and overwrite check)
- Document the release process in `docs/RELEASE.md`

**1.3.4 — Deploy updated image to devnet** ✅ (0.5 day)
- Build and push new versioned image (v1.0.0)
- Deploy to devnet via `deploy.yml` workflow
- Verify all 4 devnet validators expose `pubkey_validator` in `/crawl` response
- Verify consensus stability after upgrade

**1.3.5 — Add iptables DDoS protection to devnet validators** ✅ (0.5 day)
- Add rate limiting rules to the validator provisioning section of `deploy.yml`: 50 concurrent connections per IP (`connlimit`), 100 new connections per second (`limit`) on port 2559 — matching the rules already in place on RPC nodes
- Why this is safe at any network scale: rate limits are per source IP, not global. Each peer maintains exactly 1 persistent TCP connection, so each source IP uses 1 of the 50 allowed connections. Whether the network has 10 or 1,000 validators, each source IP still shows 1 connection per validator.
- Updated `docs/NodeSetup.md` with a firewall hardening section (UFW + iptables) so external validators following the guide get the same protection as foundation-operated nodes
- Deployed to devnet and verified on all 4 validators:
  - UFW active with only SSH (22) and peer (2559) allowed
  - iptables rules in correct order on port 2559 (ESTABLISHED→ACCEPT, connlimit→DROP, rate-limit→ACCEPT, NEW→DROP)
  - Consensus stability maintained, no peers dropped

**1.3.6 — Testnet rollout, iptables, and community notification** ✅ (1-2 days)
- **Foundation testnet validators** — update one at a time via `update.yml` rolling update to v1.0.0. Each validator must reach `proposing` state and maintain consensus before proceeding to the next. With 5 foundation validators in a 41-node topology, losing one temporarily during the update does not risk consensus (PFTL tolerates up to ~30% of UNL offline). Monitor:
  - `server_info` returns `proposing` state after each update
  - Peer count remains stable across the full topology
  - VHS agreement scores do not drop during or after the rollout
  - `/crawl` response includes `pubkey_validator` on each updated validator
- **Apply iptables to testnet validators** — SSH into each foundation testnet validator and apply the same UFW + iptables rules verified on devnet. Verify peer stability and VHS crawler access after each node.
- **Domain verification for foundation validators** — complete domain verification for the `postfiat.org` domain on all foundation validators using the `validator-keys set_domain` workflow documented in `docs/NodeSetup.md`. Publish the attestation at `https://postfiat.org/.well-known/pft-ledger.toml` and verify it resolves in the explorer.
- **Community notification** — post in the Discord `#validator-ops` channel with:
  - What changed: postfiatd v1.0.0 introduces the `/crawl` endpoint update that exposes `pubkey_validator`, enabling the Dynamic UNL scoring pipeline to resolve validator IPs for geolocation and ISP identification. This release also includes upstream security fixes and improvements merged from rippled (see M1.3.2 audit). This is the first formally versioned release of postfiatd.
  - What validators need to do: pull the latest Docker image (`docker compose pull && docker compose up -d`) and verify with `docker exec postfiatd postfiatd server_info` that the node returns to `proposing` or `full` state.
  - Security hardening: validators should configure UFW and iptables rate limiting as documented in the updated [NodeSetup.md](https://github.com/postfiatorg/postfiatd/blob/main/docs/NodeSetup.md#2-configure-firewall). Without these rules, admin ports (5005, 6006, 50051) are exposed to the public internet and the peer port (2559) has no connection flood protection. Provide the exact commands from NodeSetup.md in the announcement so validators can copy-paste without navigating to the docs.
  - Why it matters: the Dynamic UNL scoring pipeline needs `/crawl` to map validators to their IPs for geographic diversity scoring. Validators running older images will have `ip: null` in the scoring snapshot, which means the LLM cannot assess their geographic contribution to network decentralization.

**Deliverables:**
- postfiatd with `/crawl` IP exposure fix
- Audit document of rippled 3.0.0+ changes with inclusion decisions
- Automated versioned Docker image builds
- All devnet nodes running v1.0.0 with iptables verified
- All foundation testnet validators updated to v1.0.0 with iptables applied
- `docs/NodeSetup.md` updated with firewall hardening section for external validators
- Discord `#validator-ops` announcement posted with update instructions and security hardening steps
- iptables rate limiting on all foundation validators, verified on devnet before testnet rollout

---

### Milestone 1.4: Data Collection Pipeline

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.1, 1.3 | **Status:** Complete

**Goal:** Build the service that collects all validator data needed for scoring and produces a structured JSON snapshot.

**Data flow:**
```
┌───────────┐     ┌─────────────┐     ┌──────────────────┐
│  VHS API  │────►│             │     │                  │
│           │     │             │     │                  │
├───────────┤     │   Data      │     │   Structured     │
│  /crawl   │────►│   Collector │────►│   JSON Snapshot  │
│  :2559    │     │   Service   │     │   (all validators│
├───────────┤     │             │     │    with profiles)│
│  ASN      │────►│             │     │                  │
├───────────┤     │             │     │                  │
│  DB-IP    │────►│             │     │                  │
└───────────┘     └─────────────┘     └──────────────────┘
```

**IP resolution:** The VHS API provides validator performance data (by master_key/signing_key) and network topology (node IPs by node_public_key), but no mapping between them — these are separate cryptographic key systems. To resolve validator IPs, the scoring service directly probes each topology node's `/crawl` endpoint on port 2559. The `/crawl` response's `server.pubkey_validator` field identifies which nodes are validators and which master_key they hold. The postfiatd code change to expose `pubkey_validator` was completed in M1.3 (`d87fb3fca0`). Validators running the updated image will expose their identity; those on older versions will have `ip: null`.

**Steps:**

**1.4.1 — VHS data collection** ✅ (1-2 days)
- Implement `VHSClient` class that calls the VHS API:
  - `GET /v1/network/validators` — all known validators with agreement scores, domains, versions
- Parse responses into Pydantic `ValidatorProfile` models
- Handle: timeouts, retries with exponential backoff, VHS downtime
- No VHS changes needed — all required data is available from existing endpoints

**1.4.2 — Validator IP resolution via `/crawl` endpoint** ✅ (1-2 days)
- Implement `CrawlClient` class that resolves validator IPs by hitting the `/crawl` endpoint on each topology node
- For each IP from VHS topology, call `GET https://<ip>:2559/crawl` — port 2559 (peer protocol) is open on all network nodes
- Parse `response.server.pubkey_validator` to identify which nodes are validators
- Match the returned master key against VHS validators to build the IP → validator mapping
- **Prerequisite:** A postfiatd code change is required first — the current `/crawl` response excludes `pubkey_validator` because the crawl handler in `OverlayImpl::getServerInfo()` passes `admin=false` to `NetworkOPs::getServerInfo()`, which gates `pubkey_validator` behind `if (admin)`. The fix adds the validator key directly in the crawl handler (see `postfiatd/src/xrpld/overlay/detail/OverlayImpl.cpp:765-790`). Until all nodes upgrade, validators running older versions will not expose their identity.
- Handle: connection timeouts (some nodes may be unreachable), self-signed TLS certificates, nodes that don't expose `pubkey_validator` (older versions)
- Validators whose IP cannot be resolved get `ip: null` — the LLM scores them with unknown location

**1.4.3 — ASN lookup for ISP/provider identification** ✅ (0.5-1 day)
- Implement `ASNClient` class using pyasn (local BGP table, selected in Milestone 0.4)
- For each resolved validator IP: get AS number, ISP/organization name (e.g., "DigitalOcean", "Hetzner")
- This data is public (WHOIS/RIR) and freely publishable — included in the IPFS snapshot
- Cache results (ASN data changes infrequently — cache for 24h)
- Validators with `ip: null` get `asn: null`

**1.4.4 — Country-level geolocation via DB-IP Lite** ✅ (0.5 day)
- Implement `GeoIPClient` class using DB-IP Lite local database (MMDB format, CC BY 4.0)
- For each resolved validator IP: get country (sufficient for geographic diversity scoring)
- This data is freely publishable — included in the IPFS snapshot and available to Phase 2 validators
- DB-IP Lite database baked into Docker image alongside ASN data (~24 MB, refresh quarterly)
- No API key or account required — direct download from db-ip.com
- Validators with `ip: null` get `geolocation: null`

**1.4.5 — Data collector with raw evidence archival** ✅ (1-2 days)
- Implement `DataCollectorService` in `services/collector.py` that orchestrates all data collection clients and produces a complete `ScoringSnapshot`
- Collection sequence:
  1. Call VHS → get validators + topology (capture raw responses)
  2. Call Crawl → resolve validator IPs using topology (capture raw probe results)
  3. Call ASN → enrich validators with provider info (capture raw lookup results)
  4. Call DB-IP → enrich validators with country-level geolocation (capture raw lookups)
  5. Package everything into a `ScoringSnapshot`
- Modify VHS client to return both parsed results and raw JSON response (tuple return)
- For ASN, DB-IP, and Crawl: the collector assembles raw evidence records from individual lookup results
- Archive raw API responses in the `raw_evidence` database table (new migration 003):
  - One row per data source per round: `vhs_validators`, `vhs_topology`, `crawl_probes`, `asn_lookups`, `geoip_lookups`
  - Each row stores: `round_number`, `source`, `raw_data` (JSONB), `content_hash` (SHA-256), `publishable` (boolean), `captured_at`
  - `publishable` flag: true for all sources (VHS, ASN, crawl, DB-IP all use freely publishable data)
  - No FK to `scoring_rounds` — linked by `round_number`, FK can be added when the orchestrator (M1.9) manages round lifecycle
- This creates a verifiable audit chain: raw data → normalization → snapshot → scoring
- All data in the snapshot is publishable: ASN/ISP from public WHOIS data, country from DB-IP Lite (CC BY 4.0)
- Identity fields will be added to the snapshot once the identity verification design is finalized (see M3.5)
- Compute SHA-256 hash of the snapshot JSON (for on-chain reference)

**Deliverables:**
- `DataCollectorService` that produces a complete `ScoringSnapshot`
- VHS, Crawl, ASN, and DB-IP client implementations
- `raw_evidence` database table (migration 003)
- Raw evidence archival integrated into the collector
- Snapshot JSON schema documented (with data source attribution)
- Unit tests with mocked API responses

---

### Milestone 1.5: LLM Scoring Integration

**Duration:** ~4-5 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.1, 1.4 | **Status:** Complete

**Goal:** Build the service that sends validator data to the LLM (via Modal) and parses the scored output.

**Data flow:**
```
┌──────────────────┐     ┌──────────────┐     ┌──────────────────┐
│   JSON Snapshot  │────►│   Modal      │────►│   Scored Output  │
│   (all validator │     │   Serverless │     │   - Score 0-100  │
│    profiles)     │     │   Endpoint   │     │   - Reasoning    │
│                  │     │   (LLM)      │     │   - Ranked list  │
└──────────────────┘     └──────────────┘     └──────────────────┘
```

**Steps:**

**1.5.1 — Modal client** ✅ (1-2 days)
- Implement `ModalClient` class:
  - OpenAI-compatible API (`/v1/chat/completions`) for synchronous inference
  - Handle: cold starts (endpoint scaling up — can take ~5 minutes), timeouts, retries
  - Configure: temperature 0, max tokens, JSON response format
- Test with the benchmark prompt from Phase 0

**1.5.2 — Scoring prompt construction** ✅ (1-2 days)
- Implement `PromptBuilder` class that constructs the scoring prompt from a `ScoringSnapshot`
- The PromptBuilder:
  - Takes a `ScoringSnapshot` as input (not raw dicts)
  - Strips `master_key`, `signing_key`, and `ip` from each validator — replaced with anonymous IDs (`v001`, `v002`, ...) to prevent LLM bias
  - Returns both the `messages` list (for the ModalClient) and the ID-to-master-key mapping (for remapping scores back to real keys)
  - Loads the prompt template from `prompts/scoring_v1.txt` at init time (template doesn't change during runtime)
  - No separate topology data — per-validator ASN and geolocation fields make network-level topology redundant for diversity assessment
- The prompt template (`prompts/scoring_v1.txt`) must be updated from the Phase 0 test version to reflect Phase 1 data:
  - System prompt: scoring dimensions and weights (from the design spec, already solid)
  - User prompt: validator data now includes ASN (ISP/provider name) and country-level geolocation (from DB-IP Lite) — update the input description and remove the Phase 0 caveat about geolocation not being available
  - Remove the `{topology_data}` placeholder — replaced by per-validator geolocation and ASN fields
  - Add explicit penalty policies for null/missing fields:
    - `ip: null` (unresolvable via `/crawl`): penalize — an unresolvable validator cannot be assessed for geographic diversity, and the inability to be crawled is itself a negative signal
    - Old software version: penalize under software diligence — failure to upgrade blocks IP resolution and degrades network observability
    - `asn: null` / `geolocation: null` (derived from missing IP): penalize — unknown infrastructure concentration is a risk, not a neutral state
    - Missing domain / unverified domain: penalize under identity — no domain attestation means no public accountability
    - Zero or near-zero agreement scores: penalize heavily — the validator is not actively contributing to consensus
    - `identity: null`: treat as neutral on testnet (identity verification deferred to M3.5)
    - Unprofileable validators are a liability, not an unknown quantity
  - Verify the prompt fits within the model's context window
- Version the prompt (stored as a template, version tracked in config)

**1.5.3 — Response parsing and validation** ✅ (1-2 days)
- Parse the LLM's JSON response into `ScoringResult` models
- Validate:
  - All validators in the snapshot received a score
  - Scores are in range 0-100
  - Reasoning is present and non-empty
  - JSON structure matches expected schema
- Handle: malformed JSON (retry once), missing validators (flag and log), out-of-range scores (clamp and log)

**1.5.4 — UNL inclusion logic** ✅ (1-2 days)
- Implement the mechanical UNL inclusion rule from the design:
  1. Sort validators by score descending
  2. Apply cutoff threshold (configurable, e.g., score >= 40)
  3. If <= 35 validators above cutoff → all are on the UNL
  4. If > 35 above cutoff → top 35 by score
  5. Remaining are alternates, ranked in order
- **Churn control — minimum score gap for replacement:**
  - A challenger only displaces an incumbent UNL validator if the challenger's score exceeds the incumbent's score by at least X points (configurable, e.g., 5-10)
  - If the gap is smaller, the incumbent stays regardless of absolute ranking
  - This prevents UNL oscillation caused by minor score fluctuations between rounds
  - The exact gap value will be determined during devnet testing (Milestone 1.10) by measuring natural score variance across rounds
  - On the first round (no previous UNL exists), the rule does not apply — the initial UNL is set purely by score ranking
- Output: ordered list of validator public keys for the UNL, plus alternates

**Deliverables:**
- `LLMScorerService` that takes a snapshot and returns scored + ranked validators
- Modal client with cold start handling
- Prompt template (versioned) with explicit diversity dimension guidance
- UNL inclusion logic with configurable threshold and minimum score gap for replacement
- Unit tests with mocked Modal responses

---

### Milestone 1.6: VL Generation (Signed Validator List)

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.5 | **Status:** Complete

**Goal:** Generate a signed VL JSON file in the same format that postfiatd already understands, using the existing publisher key infrastructure.

**Critical insight:** Testnet nodes already fetch a signed VL from `https://postfiat.org/testnet_vl.json` and verify it against the publisher key `ED3F1E...`. The scoring service will generate VLs in this exact format, so **no C++ changes are needed in postfiatd for Phase 1**.

**Data flow:**
```
┌──────────────┐     ┌──────────────┐     ┌────────────────────────┐
│ Ranked       │     │ VL Generator │     │ Signed VL JSON         │
│ Validator    │────►│ (port of     │────►│ (same format as        │
│ List         │     │  generate_   │     │  generate_vl.py output)│
│ (from 1.3)   │     │  vl.py)      │     │                        │
└──────────────┘     └──────────────┘     └────────────────────────┘
                                                     │
                                          ┌──────────┴──────────┐
                                          ▼                     ▼
                                    Upload to URL         Serve via
                                    (HTTPS endpoint)      scoring service
```

**Steps:**

**1.6.1 — Port generate_vl.py signing logic** ✅ (2-3 days)
- Port the VL generation logic from `postfiatd/scripts/generate_vl.py` into the scoring service
- Key functions to port:
  - `decode_token()` / `parse_manifest()` — decode publisher token, extract keys from manifest (XRPL STObject binary format)
  - `sha512_half()` — XRPL SHA-512-Half (first 32 bytes of SHA-512)
  - `sign_blob()` — sign VL blob with secp256k1 ECDSA (SHA-512-Half digest, DER-encoded, canonical low-S)
  - `to_ripple_epoch()` — convert dates to XRPL epoch (seconds since Jan 1, 2000 UTC)
  - VL JSON assembly (v2 format: `public_key`, `manifest`, `blobs_v2[{blob, signature}]`, `version: 2`)
- **Publisher token:** `VL_PUBLISHER_TOKEN` env var (base64 blob containing the manifest + ephemeral signing key secret). Separate keys per environment — never share publisher keys between devnet and testnet.
- **Validator manifests:** Fetched from the RPC node's `manifest` command (one call per UNL validator, up to 35). VHS does not return the raw base64 manifest blob needed for VL assembly. Requires new `RPC_URL` config setting pointing to the environment's RPC node.
- **Expiration:** Configurable via `VL_EXPIRATION_DAYS` (default: 500 days). Each scoring round generates a VL with expiration pushed out from the current date. Long expiration is a safety net — if the scoring service stops publishing, nodes keep trusting the last VL for the full window.
- Input: ranked list of validator master keys (from UNL selector) + manifests (from RPC)
- Output: signed VL JSON (v2 format) with incrementing sequence number
- **Note:** Set the remaining GitHub secrets at this point: `DEVNET_PFTL_WALLET_SECRET`, `DEVNET_PFTL_MEMO_DESTINATION`, `DEVNET_VL_PUBLISHER_TOKEN` (and testnet equivalents)

**1.6.2 — Sequence management** ✅ (0.5-1 day)
- Track the VL sequence number in PostgreSQL (must always increment — nodes reject <= current)
- On each scoring round: read last sequence, increment, use for new VL
- Safety check: before publishing, verify new sequence > last published sequence

**1.6.3 — VL storage and serving endpoint** ✅ (0.5-1 day)
- Extend the `vl_sequence` table with a `vl_data JSONB` column to store the latest signed VL (1:1 with the sequence — they're written in the same transaction)
- Add `store_vl(conn, vl_data)` function to persist the signed VL JSON to the database
- Add `GET /vl.json` endpoint that reads the latest VL from PostgreSQL and returns it as JSON (404 if no VL exists yet)
- Each environment has its own scoring service instance, so the domain differentiates:
  - Devnet: `https://scoring-devnet.postfiat.org/vl.json`
  - Testnet: `https://scoring-testnet.postfiat.org/vl.json`
- The endpoint is live as soon as the service is deployed, but returns 404 until the orchestrator (M1.9) runs a scoring round and writes a VL

**Deliverables:**
- `VLGeneratorService` that produces a signed VL JSON from a ranked validator list
- Sequence number tracking in PostgreSQL
- VL storage and serving endpoint (`GET /vl.json`)

**Security note:** The publisher signing key is the most sensitive secret in this system. It must be stored securely (environment variable, never in code or logs). If this key is compromised, an attacker could publish a malicious UNL. Required mitigations for Phase 1:
- Separate keys for devnet and testnet (never share signing keys across environments)
- Publisher key is fully configurable via `VL_PUBLISHER_TOKEN` env var — key rotation is an env var change + node config update + rolling restart
- Access logging for every signing operation (log round number, timestamp, VL hash — never log the key itself)
- Manual offline emergency signing tool: a standalone CLI script that can sign and publish a VL without the scoring service running (for use if the service is compromised or unavailable)
- For mainnet (future): upgrade to HSM or Vault transit for key storage

**Testnet transition plan (executed during M1.13):**
- Testnet nodes currently fetch VL from `https://postfiat.org/testnet_vl.json` with publisher master key `ED3F1E0DA736FCF99BE2880A60DBD470715C0E04DD793FB862236B070571FC09E2`.
- **Publisher-key continuity:** the scoring service reuses this exact master key and signing manifest on testnet, so the transition is a URL-content overwrite rather than a trust-root rotation. Community validators need no configuration change, no restart, and no coordination. No postfiatd release is required.
- Transition sequence is codified in M1.13: deploy the scoring service to testnet in dry-run mode, observe for 2-3 weekly rounds, confirm go-live criteria, publish the first live round with an extended `effective_lookahead_hours` (24) so operators have a full day to review before activation, and deliver the content at the existing URL (`postfiat.org/testnet_vl.json`) via the Pages publisher built in M1.10.7 (GitHub Contents API push to `postfiatorg/postfiatorg.github.io/testnet_vl.json`). The scoring service continues to serve a parallel copy at `scoring-testnet.postfiat.org/vl.json` for tooling that prefers the scoring-native domain, but validators consume only the Pages URL.
- The key custody chain is constrained to the foundation's blockchain engineer and a second principal. The previous publishing location for `testnet_vl.json` should cease signing once the scoring service's publication path is confirmed stable.

---

### Milestone 1.7: IPFS Audit Trail Publication

**Duration:** ~2-3 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestones 1.4, 1.5 | **Status:** Complete

**Goal:** Publish the full scoring audit trail to IPFS after each round.

**Steps:**

**1.7.1 — IPFS client** ✅ (1-2 days)
- Implement `IPFSClient` class that pins content to the self-hosted IPFS node:
  ```
  POST https://ipfs-testnet.postfiat.org/api/v0/add
  Authorization: Basic <base64(admin:password)>
  Content-Type: multipart/form-data
  ```
- Support pinning JSON files and directory structures
- Return the CID (Content Identifier) for each pinned item
- Handle: upload failures, retries, timeout

**1.7.2 — Audit trail assembly and publication** ✅ (1-2 days)
- After each scoring round, publish to IPFS:
  ```
  round_<N>/
  ├── snapshot.json           # Normalized validator data snapshot (scorer input)
  ├── raw/                    # Raw API responses (verifiable audit trail)
  │   ├── vhs_validators.json # Raw VHS response, timestamped
  │   ├── vhs_topology.json   # Raw VHS topology response
  │   ├── crawl_probes.json   # Raw /crawl responses (IP resolution evidence)
  │   ├── asn_lookups.json    # Raw ASN lookup responses
  │   └── geoip_lookups.json  # Raw DB-IP country lookups
  ├── scoring_config.json     # Model version, weight hash, prompt version, parameters
  ├── scores.json             # LLM output (scores + reasoning for each validator)
  ├── unl.json                # Final UNL (list of included validators + alternates)
  └── metadata.json           # Round number, timestamps, hashes, attribution
  ```
- All raw data sources are freely publishable (VHS, ASN, DB-IP Lite under CC BY 4.0)
- **DB-IP attribution requirement:** `metadata.json` must include `"geolocation_attribution": "IP geolocation by DB-IP.com"` to satisfy the CC BY 4.0 license terms
- Pin the directory and get the root CID
- Store assembled files in PostgreSQL (`audit_trail_files` table) for HTTPS fallback serving
- Serve audit trail artifacts over plain HTTPS as a fallback: `GET /api/scoring/rounds/<N>/<file_path>` (e.g., `https://scoring-testnet.postfiat.org/api/scoring/rounds/1/metadata.json`)
- Store CID in PostgreSQL linked to the round
- Note: validators can fetch by CID through any IPFS gateway, not just the foundation's

**Deliverables:**
- `IPFSPublisherService` that assembles the audit trail, pins to IPFS, and stores files for HTTPS fallback
- Database migration for `audit_trail_files` table
- `GET /api/scoring/rounds/{round_number}/{file_path}` HTTPS fallback endpoint
- Audit trail directory structure defined and implemented

---

### Milestone 1.8: On-Chain Memo Publication

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestones 1.6, 1.7 | **Status:** Complete

**Goal:** Publish a scoring round receipt on-chain as a memo transaction. The IPFS CID in the memo is the integrity anchor — it's a content-addressed hash of the full audit trail, so anyone can fetch and verify the evidence independently.

**Steps:**

**1.8.1 — PFTL client and memo format** ✅ (1-2 days)
- Implement `PFTLClient` following the scoring-onboarding pattern:
  - Async client using `xrpl-py` (`AsyncJsonRpcClient`, `autofill`, `submit_and_wait`)
  - Wallet creation from hex private key via `ecpy` secp256k1 derivation
  - Payment transaction (1 drop) with hex-encoded memo type and data
  - Returns `(success, tx_hash, error)` tuple
- Memo type: `pf_dynamic_unl` (hex-encoded via `str_to_hex`)
- Memo data format:
  ```json
  {
    "type": "pf_dynamic_unl",
    "ipfs_cid": "Qm...",
    "vl_sequence": 42
  }
  ```
  The IPFS CID is the integrity anchor — all round details (scores, model, prompt version, validators) are in the audit trail reachable via the CID
- `OnChainPublisherService` wraps the client with a `publish()` method that takes round outputs, builds the memo, submits, and returns the transaction hash
- Transaction hash stored in PostgreSQL by the orchestrator (M1.9)
- Retry logic handled by the orchestrator state machine (M1.9), not this service

**Deliverables:**
- `PFTLClient` for PFTL chain transactions (`clients/pftl.py`)
- `OnChainPublisherService` that builds and submits memo transactions (`services/onchain_publisher.py`)
- New dependencies: `xrpl-py`, `ecpy`
- Test suite covering wallet creation, memo building, transaction submission, error handling

---

### Milestone 1.9: Scoring Orchestrator & Scheduler

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.4-1.8 | **Status:** Complete

**Goal:** Wire all services together into a state machine orchestrator with idempotent steps, scheduled and on-demand execution.

**Steps:**

**1.9.1 — State machine orchestrator** ✅ (2-3 days)
- Implement `ScoringOrchestrator` as an explicit state machine with these states:
  ```
  COLLECTING → SCORED → SELECTED → VL_SIGNED →
  IPFS_PUBLISHED → ONCHAIN_PUBLISHED → COMPLETE
                                          ↓ (any step)
                                        FAILED
  ```
- Each step is **idempotent** — rerunning from any state produces the same result
- On failure: record which state failed, resume from that state on retry (don't re-run scoring if IPFS upload failed)
- Round metadata tracked in `scoring_rounds` table:
  ```
  id, round_number, state (enum of above states),
  snapshot_hash, ipfs_cid, onchain_tx_hash, vl_sequence,
  started_at, completed_at, error_message,
  state_transitions (JSONB array of {state, timestamp, result})
  ```
- Every state transition is logged for audit
- **Capabilities:**
  - `dry_run` — run the full pipeline without publishing (no IPFS pin, no on-chain memo, no VL upload)
  - `replay_round` and `rebuild_from_raw` deferred to M1.10.10 — implement during prompt iteration when debugging tools are needed

**1.9.2 — Scheduler** ✅ (0.5-1 day)
- Background task in the FastAPI lifespan that checks every 5 minutes whether a new round is due
  - Default cadence: every 168 hours (weekly), configurable via `SCORING_CADENCE_HOURS`
  - PostgreSQL advisory lock ensures only one round runs at a time (no in-process scheduler library)
  - Determines "is it time?" from the last successful round's `completed_at` in `scoring_rounds`
  - 5-minute startup delay before the first check to let the service stabilize

**1.9.3 — Manual trigger** ✅ (0.5 day)
- API endpoint: `POST /api/scoring/trigger` — triggers an immediate scoring round in a background thread
- `POST /api/scoring/trigger?dry_run=true` — dry run mode
- Returns the round ID immediately; caller checks progress via status API (M1.9.4)
- Background thread: acquires advisory lock → runs orchestrator → releases lock in finally block
- 409 Conflict if a round is already in progress (advisory lock held)
- Admin authentication via `ADMIN_API_KEY` header; endpoint disabled if key not configured
- Stale round cleanup: before starting a new round, marks any stuck intermediate rounds as FAILED
- Replay endpoint deferred to M1.10.10

**1.9.4 — Status API** ✅ (0.5 day)
- `GET /api/scoring/rounds` — list recent rounds with status and current state
- `GET /api/scoring/rounds/<id>` — detailed round info (all hashes, CIDs, timestamps, state transition log)
- `GET /api/scoring/unl/current` — current active UNL (latest successful round)

**Deliverables:**
- `ScoringOrchestrator` as a state machine with idempotent steps
- dry_run capability (replay_round and rebuild_from_raw deferred to M1.10.10)
- Postgres-based scheduling with advisory locks
- Manual trigger + status API endpoints
- Round tracking with state transition audit log

---

### Milestone 1.10: Devnet Testing & Validation

**Duration:** ~13-19 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.2, 1.9

**Goal:** Expand devnet with diverse validators, run the full scoring pipeline end-to-end, switch devnet to a dynamically scored VL, iterate on prompt quality and stability.

**Context:** No postfiatd C++ changes are needed for Phase 1's VL fetching — the infrastructure (`[validator_list_sites]` + `[validator_list_keys]`) is already in the codebase, inherited from rippled and proven on testnet. This was independently verified by reading `ValidatorList.cpp`, `ValidatorSite.cpp`, and the `NetworkOPs` consensus path: VL updates are purely HTTP-polled by each validator (default 5-minute refresh interval), signature verification is unconditional of amendment state, and the monotonically increasing `sequence` field is the sole ordering primitive. Flag ledgers govern amendment and fee voting only, never VL updates. The `featureDynamicUNL` amendment is a Phase 3 concern only. A postfiatd v1.0.3 release is needed to fix the devnet genesis account (the previous devnet genesis was unusable for the scoring service because its secret was not locally accessible for funding the PFTL wallet and memo destination). Applying the genesis fix requires a full network reset — all validators destroyed, data volumes wiped, and redeployed from scratch with 1.0.3. All postfiatd work in this milestone is operational: tagging a v1.0.3 release with the genesis fix, resetting devnet, and rolling restart to switch from static UNL to dynamic VL fetching. There is also a 24+ hour waiting period after the network reset before the first scoring round, to allow VHS to accumulate meaningful agreement data.

**Note on validator version diversity:** Earlier iterations of this plan attempted to create software version diversity across devnet validators (v1.0.0/v1.0.1/v1.0.2). This was dropped because the genesis account reset requires all validators to run the same version (v1.0.3). Software version scoring will be validated on testnet (M1.13), where the community validator set naturally runs multiple postfiatd versions. Devnet's purpose in M1.10 is to verify the pipeline flow end-to-end, not the LLM's scoring quality.

**Steps:**

**1.10.1 — postfiatd v1.0.3 release and devnet reset** ✅ (0.5 day)
- Tag `v1.0.3` in the postfiatd repo with the devnet genesis account fix (the previous devnet genesis key was not locally accessible, making it impossible to fund the scoring service's on-chain memo wallet). Build devnet-light Docker image and create a GitHub release.
- Destroy the existing devnet infrastructure via the postfiatd `destroy.yml` workflow, then redeploy via `deploy.yml` with the v1.0.3 image. All 4 foundation validators come up with fresh data volumes on the new genesis ledger.
- Fund the scoring service PFTL wallet and memo destination account from the new (known) genesis account using existing transfer scripts.

**1.10.2 — Expand devnet validator set** ✅ (1 day)
- Provision 2 additional validator nodes on Vultr in different regions for geographic and ASN diversity:
  - 1 validator in Europe (Frankfurt)
  - 1 validator in Asia (Singapore)
- These are temporary test validators — manually provisioned, not added to `deploy.yml` or GitHub secrets. They will be destroyed after devnet testing is complete.
- Setup per validator:
  1. Create Vultr instance (light tier: 2 vCPU, 4 GB RAM)
  2. SSH in, install Docker
  3. Generate a validator token: run `validator-keys create_keys` + `validator-keys create_token` inside any existing postfiatd container, save the output
  4. Pull the devnet light image (`devnet-light-1.0.3`)
  5. Create a docker-compose file with the validator token injected and at least one existing devnet validator IP as a peer
  6. Give the new validators the same `validators-devnet.txt` as the existing 4 (they trust the existing UNL — one-way trust is fine, the existing 4 don't need to trust them back)
  7. Start the container
- Do NOT add the new validators to the existing static UNL — the dynamic VL will decide their inclusion later
- Verify both new validators sync, produce validations, and VHS discovers them
- Let them run for 24+ hours before the first scoring round so VHS accumulates meaningful agreement data
- Target diversity profile across all 6 validators:
  - 4 existing: US/Vultr, domain attested, strong agreement history
  - 1 new: Europe/Vultr, no domain, fresh agreement history
  - 1 new: Asia/Vultr, no domain, fresh agreement history
- Score differentiation is organic: the existing 4 have domain attestation and longer agreement history, the new 2 have none but bring real geographic and ASN diversity.

**1.10.3 — Publisher key generation** ✅ (1 hour)
- Generate a new publisher key pair for devnet using `validator-keys create_keys` + `validator-keys create_token` (existing C++ tool in the postfiatd build)
- Store the token in `DEVNET_VL_PUBLISHER_TOKEN` GitHub secret (used by scoring service deploy workflow)
- Record the master public key — it goes into the postfiatd config later (1.10.8)
- Configure the scoring service with the publisher token in its devnet environment

**1.10.4 — Deploy scoring service to devnet** ✅ (1-2 hours)
- **Prerequisite: set all GitHub secrets** for the `deploy-devnet.yml` workflow before pushing. The workflow injects these into the runtime `.env` at deploy time:
  - `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` — Docker Hub image push/pull
  - `VULTR_DEVNET_HOST`, `VULTR_SSH_USER`, `VULTR_SSH_KEY` — SSH into devnet scoring instance
  - `DEVNET_DB_PASSWORD` — PostgreSQL password
  - `DEVNET_PFTL_WALLET_SECRET`, `DEVNET_PFTL_MEMO_DESTINATION` — on-chain memo transactions
  - `MODAL_ENDPOINT_URL` — LLM scoring endpoint
  - `IPFS_API_URL`, `IPFS_API_USERNAME`, `IPFS_API_PASSWORD`, `IPFS_GATEWAY_URL` — IPFS audit trail
  - `DEVNET_VL_PUBLISHER_TOKEN` — VL signing (generated in 1.10.3)
  - `DEVNET_ADMIN_API_KEY` — manual scoring trigger authentication
- Create `devnet` branch from main, push to trigger deploy workflow
- Verify automated deployment succeeds: image built, pushed to Docker Hub, deployed to Vultr
- Verify health endpoint: `curl https://scoring-devnet.postfiat.org/health`
- Verify API docs: `https://scoring-devnet.postfiat.org/docs` (FastAPI auto-docs)

**1.10.5 — First scoring round** ✅ (1 day)
- Trigger a manual scoring round via `POST /api/scoring/trigger`
- Verify each pipeline step:
  - Data collected from VHS (check snapshot — do all 6 validators appear?)
  - IP resolution via `/crawl` (check that new validators have IPs resolved)
  - ASN and geolocation enrichment (new validators should show different countries/ASNs)
  - LLM called successfully (check scores — are they differentiated across the 6 validators?)
  - UNL selection (check that 3 validators were selected from the 6)
  - VL generated, signed, and served at `/vl.json`
  - Audit trail pinned to IPFS (fetch via gateway, verify content)
  - HTTPS fallback serving works (`GET /api/scoring/rounds/<N>/metadata.json`)
  - Memo transaction submitted on-chain (verify via RPC `account_tx`)
- Set up secondary IPFS pinning (Pinata or web3.storage) for redundancy

**1.10.6 — VL effective-timestamp lookahead** ✅ (1-2 days)

*Deviation from original plan:* The original VL generator omitted the optional `effective` field in the v2 blob, which caused published VLs to activate immediately upon each validator's next HTTP poll. Because different validators poll at slightly different times (default 5-minute refresh interval), this created a propagation window of up to 5 minutes during which validators could temporarily disagree on the trust set. Postfiatd's `ValidatorList::verify` at `ValidatorList.cpp:1406-1448` fully supports the `effective` (internally `validFrom`) field: blobs with `validFrom > closeTime` are queued in `remaining` and promoted to `current` by `updateTrusted` at `ValidatorList.cpp:1946-2003` only when `closeTime >= validFrom`. Using this mechanism allows all validators to fetch a pending blob well in advance and simultaneously activate it on the same consensus tick, collapsing the propagation window to sub-second consensus precision.

*Code change:* Extend `scoring_service/services/vl_generator.py` so the inner blob includes `effective` computed as `to_ripple_epoch(now + timedelta(hours=effective_lookahead_hours))`. Add a new `VL_EFFECTIVE_LOOKAHEAD_HOURS` setting in `scoring_service/config.py` (default: 1 hour) and thread it through the orchestrator's VL signing step. Expose the parameter on `generate_vl(...)` so callers can override per invocation.

*Parameterization rules:*
- **Automated scheduler rounds:** use the default `VL_EFFECTIVE_LOOKAHEAD_HOURS` (1 hour). One hour is comfortably longer than the 5-minute poll interval and the 30-second error-retry interval, so every validator has multiple opportunities to fetch the pending blob before activation.
- **M1.10.8 parity transition VL:** lookahead **must be 0** (immediate activation). Validators are migrating from the static `[validators]` block to the URL mechanism with no cached VL state; if the first VL they fetch is pending, they have no trusted set and consensus stalls until the scheduled activation.
- **Admin override endpoints (M1.11):** accept an optional `effective_lookahead_hours` parameter, defaulting to 1 hour, with 0 permitted for true-emergency immediate activation.
- **First testnet live round (M1.13):** use 24 hours to give operators a full day to inspect the blob and invoke an admin rollback before activation.

*Tests:* Unit tests for the generator asserting the `effective` field is present, correctly computed from the passed lookahead, and equals the current ripple epoch when `effective_lookahead_hours=0` (immediate activation). Extend the end-to-end orchestrator test to verify the VL published by an automated round carries an `effective` in the future and would be held as pending by a downstream consumer.

**1.10.7 — VL distribution to `postfiatorg.github.io`** ✅ (2-3 days)

*Background:* `postfiat.org/testnet_vl.json` is served by GitHub Pages from the `postfiatorg/postfiatorg.github.io` repository, not by the scoring service. For testnet transition (M1.13) to avoid any community validator configuration change, the scoring service must write each round's signed VL into that repository under the matching path. The same mechanism is set up on devnet first to rehearse the distribution pipeline end-to-end before testnet depends on it — this is a core piece of what "parity" means in M1.10.8.

*New `VL_DISTRIBUTED` orchestrator stage:* Insert a new stage between `IPFS_PUBLISHED` and `ONCHAIN_PUBLISHED` in `scoring_service/services/orchestrator.py`. The new stage writes the signed VL blob to `postfiatorg/postfiatorg.github.io` via the GitHub Contents API (`PUT /repos/{owner}/{repo}/contents/{path}`), waiting for the commit to succeed. Ordering rationale: if Pages fails, the on-chain memo has not yet been spent, so the round fails cleanly without burning a transaction that would claim a VL was distributed when it was not.

*New `scoring_service/clients/github_pages.py` client:* Encapsulates the Contents API call, including:
- Fetch the current file SHA via `GET /repos/{owner}/{repo}/contents/{path}` (required by the Contents API for updates).
- `PUT` the new file with base64-encoded content, the commit message (`"Scoring round N — VL sequence X"`), and the fetched SHA.
- Configurable retry with exponential backoff on transient 5xx.
- Treats 404 on the initial SHA fetch as "first publish" and proceeds without a `sha` field.

*New environment variables* (separate values per environment):
- `GITHUB_PAGES_TOKEN` — fine-grained PAT with `contents:write` on the target repo only.
- `GITHUB_PAGES_REPO` — `postfiatorg/postfiatorg.github.io`.
- `GITHUB_PAGES_FILE_PATH` — `devnet_vl.json` for devnet, `testnet_vl.json` for testnet.
- `GITHUB_PAGES_BRANCH` — `main`.
- `GITHUB_PAGES_COMMIT_AUTHOR_NAME` / `GITHUB_PAGES_COMMIT_AUTHOR_EMAIL` — identifies the service account in commit metadata.
Added to `scoring_service/config.py`, `.env.example`, the devnet and testnet deploy workflows, and the GitHub org secrets list in `README.md`.

*Database:* Extend `scoring_rounds` with a nullable `github_pages_commit_url` column via a new numbered migration. Populated during the `VL_DISTRIBUTED` stage; available for the explorer's audit-trail panel.

*Service account and credential setup:*
1. Create a `postfiat-scoring-bot` GitHub user account and invite it to the `postfiatorg` organization with the minimum role required to hold a PAT on org repos.
2. Generate a fine-grained PAT under that user. Repository access: **only** `postfiatorg/postfiatorg.github.io`. Repository permissions: `Contents: Read and write`. Expiration: 1 year.
3. Add the PAT as `DEVNET_GITHUB_PAGES_TOKEN` and `TESTNET_GITHUB_PAGES_TOKEN` in the scoring service's GitHub Actions secrets (consumed by the respective deploy workflows).
4. Add a calendar reminder ~60 days before expiration to rotate. Rotation procedure goes into `docs/ScoringOperations.md`.

*Tests:* Unit tests mocking the Contents API (success, SHA-mismatch retry, 404-first-publish, 5xx backoff, 4xx fail-fast). End-to-end test against a throwaway test repo to exercise real Contents API authentication before deploying to production.

*Deliverables:*
- `scoring_service/clients/github_pages.py` client
- `VL_DISTRIBUTED` orchestrator stage with full failure handling
- Per-environment env var configuration
- `github_pages_commit_url` column on `scoring_rounds`
- `postfiat-scoring-bot` service account with fine-grained PAT
- Test coverage including an end-to-end exercise against a test repo

**1.10.8 — Devnet parity: static-to-URL config switch** ✅ (1-2 days)

*Prerequisite:* The Pages publisher from M1.10.7 is operational on the devnet deployment and can write to `postfiatorg.github.io/devnet_vl.json`. For this step, the published VL is produced via a one-shot admin trigger with `effective_lookahead_hours=0` and a UNL matching the current static 4-validator set, so the config mechanism change is isolated from any UNL content change.

*Publish the parity VL:* Use the admin custom-UNL endpoint (from M1.11, landing before this step per the M1.11 dependency) with `master_keys` set to the 4 foundation validator master keys currently in the static `[validators]` block, `effective_lookahead_hours=0`, and a descriptive reason. The orchestrator signs the VL, pins the audit trail to IPFS, writes the VL to `postfiatorg.github.io/devnet_vl.json` via the `VL_DISTRIBUTED` stage, and publishes the on-chain memo. After the Pages commit propagates (~1-2 minutes), verify `https://postfiat.org/devnet_vl.json` returns the signed VL.

*Config change:* In the postfiatd repo, update `validators-devnet.txt` — replace the static `[validators]` block with:
```ini
[validator_list_sites]
https://postfiat.org/devnet_vl.json

[validator_list_keys]
<DEVNET_PUBLISHER_MASTER_KEY>
```
Push the config change to the postfiatd `devnet` branch to build a new devnet Docker image.

*Rolling restart — one validator at a time, non-UNL members first:*

Because the parity VL contains the same 4 validators as the static block, no UNL membership changes during this step. Each validator's trusted set before and after the restart is identical. The objective is purely to flip the config mechanism from local `[validators]` to publisher-signed `[validator_list_sites]`.

1. Restart the two non-UNL devnet test validators (Europe, Asia) first. Their status is unchanged either way — neither list trusts them — and they exercise the new fetch path.
2. Restart the 4 foundation validators one at a time. During each brief downtime, the other 3 keep producing validations and consensus holds (quorum is ceil(4 × 0.8) = 4 on the dynamic path once activated, or 3 on the interim static list, so minor timing variance is absorbed by normal retry behavior).

After all 6 validators have restarted, every node is reading its trust set from `postfiat.org/devnet_vl.json`. The UNL membership is unchanged (still the 4 foundation validators). Verify this by checking each validator's `server_info` RPC and confirming the validator list source is the Pages URL.

**1.10.9 — Devnet dynamic switch: automated rounds** ✅ (1-2 days)

*Prerequisite:* Parity step complete — all 6 devnet validators are fetching VLs from `postfiat.org/devnet_vl.json` with the 4-validator parity UNL active.

*Switch to automated scoring:* Enable the built-in scheduler (or trigger a manual automated round via `POST /api/scoring/trigger` without any override) so the next round runs the full pipeline end-to-end: data collection, LLM scoring, UNL selection with `UNL_MAX_SIZE=3`, VL signing with the default 1-hour `effective_lookahead_hours`, IPFS publication, Pages distribution, and on-chain memo.

*Observe propagation and activation:*
1. Within ~2 minutes of Pages distribution, `https://postfiat.org/devnet_vl.json` returns the new VL.
2. Within 5-10 minutes of the Pages commit (each validator's default poll interval is 5 minutes), confirm via log inspection (`docker logs` on each validator) that every devnet validator has fetched the new VL and logged the pending blob being held for activation (rippled emits `ValidatorList::verify` decision logs at this point).
3. At the scheduled activation time (T + 1 hour), every validator's `updateTrusted` rotates the pending blob to current simultaneously. Verify all 6 validators transition on the same ledger close.
4. After activation, consensus is governed by the 3 validators selected by the scoring service. Confirm the 3 selected validators are producing validations that reach quorum, and the other 3 (the dropped incumbent plus the two newcomers that weren't selected) continue running but are no longer counted toward quorum.

*Important limitation:* With `UNL_MAX_SIZE=3`, the network requires all 3 selected validators to agree (ceil(3 × 0.8) = 3). There is zero fault tolerance — if any one of the 3 goes down, the network stalls until it comes back. This is accepted for devnet testing. Testnet will run with `UNL_MAX_SIZE=35` and comfortable Byzantine headroom.

**1.10.10 — Prompt iteration and debugging tools** (2-3 days)
- Implement `replay_round(round_id)` — re-run a completed round from its saved snapshot (useful for debugging scoring output without re-collecting data)
- Implement `rebuild_from_raw(round_id)` — re-normalize from raw evidence and re-score (verifies the full evidence chain)
- Review LLM scoring output quality:
  - Are scores differentiated? (not all clustered at 85-90)
  - Does reasoning reference actual validator metrics (agreement %, version, geography)?
  - Does the LLM correctly penalize missing domain attestation?
  - Does geographic diversity factor into scoring? (validators in different countries/ASNs should contribute to network diversity)
  - Does the LLM correctly identify and penalize older software versions?
- Iterate on the prompt based on output quality
- Run 3-5 scoring rounds, compare results across rounds
- Finalize prompt version

**1.10.11 — Scoring stability testing** (1-2 days)
- Replay the same snapshot multiple times (5-10 runs) — scores should be consistent across runs (deterministic inference confirmed in Phase 0, but verify with real devnet data)
- One-candidate-added / one-candidate-removed test — existing validator scores should not shift significantly when an unrelated validator is added or removed from the snapshot
- Measure natural score variance across rounds to calibrate the minimum score gap config value for churn control
- Validate that the churn control mechanism behaves as expected: borderline validators should not oscillate between rounds

**1.10.12 — Edge case testing** (1-2 days)
- Test: what happens when VHS is down? (data collection should fail gracefully, round marked FAILED)
- Test: what happens when Modal cold-starts? (should wait — 35-min startup timeout configured)
- Test: what happens when IPFS is unreachable? (round should fail gracefully)
- Test: what happens when the GitHub Pages PUT fails (rate limit, bad token, SHA conflict)? (`VL_DISTRIBUTED` retries with backoff; persistent failure marks round FAILED without spending an on-chain memo)
- Test: what happens when PFTL node is down? (memo submission should fail, round marked FAILED)
- Test: what happens with 0 validators in VHS? (should produce empty UNL, not crash)
- Test: scheduler runs correctly at configured interval

**Deliverables:**
- 6 devnet validators with organic diversity (geography, ASN, domain, software version, agreement history)
- Multiple successful scoring rounds with differentiated scores
- Effective-timestamp lookahead mechanism implemented and verified end-to-end via devnet validator log inspection
- GitHub Pages publisher pushing VLs to `postfiatorg/postfiatorg.github.io` for devnet, with the `VL_DISTRIBUTED` orchestrator stage integrated
- All 6 devnet validators fetching dynamic VL from `postfiat.org/devnet_vl.json` (UNL_MAX_SIZE=3), with parity and dynamic-switch transitions executed as distinct steps
- Finalized scoring prompt
- Replay and rebuild debugging tools
- Edge case test results documented

---

### Milestone 1.11: Admin Override Endpoints ✅

**Duration:** ~3-5 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.10.6 (effective-timestamp lookahead) and 1.10.7 (VL distribution to Pages) | **Goal:** Provide an auditable kill-switch surface on the scoring service that lets the operator publish a specific UNL without running the automated pipeline. Required before M1.10.8 (devnet parity uses the custom endpoint to publish the seed VL) and before M1.13 so the foundation has a rehearsed emergency path ready when testnet flips live. These endpoints are temporary scaffolding for Phase 1 and Phase 2; they are removed at the Phase 3 boundary when validators begin producing the UNL via commit-reveal and the foundation is no longer the sole publisher.

**Why two endpoints:** Audit-trail clarity. The "republish arbitrary set" path and the "republish historical round" path serve different operational intents and should be distinguishable in the audit record without a post-hoc reason parse.

**Steps:**

**1.11.1 — Endpoint design and schema updates** (~0.5 day)

- Add `override_type` (nullable text: `"custom"` or `"rollback"`) and `override_reason` (nullable text) columns to the `scoring_rounds` table via a new numbered migration under `migrations/`.
- Define the request/response contracts:
  - `POST /api/scoring/admin/publish-unl/custom` — body: `{master_keys: [nHU...], reason: string, effective_lookahead_hours?: number (default 1), expiration_days?: number (default VL_EXPIRATION_DAYS)}`. Validates that every master key has a cached manifest (fetches from the RPC node if missing).
  - `POST /api/scoring/admin/publish-unl/from-round/{round_id}` — body: `{reason: string, effective_lookahead_hours?: number (default 1), expiration_days?: number (default VL_EXPIRATION_DAYS)}`. Reads `unl.json` from `audit_trail_files` for the referenced round and republishes that UNL.
- Both endpoints require `X-API-Key: <ADMIN_API_KEY>` (reuse the existing admin auth in `scoring_service/api/scoring.py`).
- Both return `202 Accepted` with the synthetic round number; publishing runs in a background thread like the existing manual trigger.

**1.11.2 — Implementation** (~1-2 days)

- New handlers in `scoring_service/api/scoring.py` that acquire the same advisory lock (`99001`) as the automated path so overrides never race the scheduler.
- New orchestrator entry points that skip COLLECTING, SCORED, and SELECTED stages but go through VL_SIGNED, IPFS_PUBLISHED, VL_DISTRIBUTED, and ONCHAIN_PUBLISHED identically to automated rounds. The override round writes a full audit trail directory (snapshot marked as override-only, scores empty, unl as specified, vl the signed blob, metadata with `override: true` and the reason string embedded), pushes the signed VL to `postfiatorg.github.io` through the same Pages publisher used by automated rounds, and emits an on-chain memo with a distinct type string `pf_dynamic_unl_override` so explorers and downstream consumers can distinguish manual republishes from automated rounds.
- As part of this work, extend the standard (non-override) memo payload emitted by `scoring_service/services/onchain_publisher.py` to include `round_number` alongside the existing `ipfs_cid` and `vl_sequence` fields. The field makes the memo self-describing for the common "I saw this memo, show me the round" workflow without requiring a downstream `vl_sequence` → `round_number` DB lookup, and costs effectively nothing in memo size. Override memos inherit the same shape with the distinct type string set.
- Store the synthetic round with `override_type` and `override_reason` populated. Set the seven-stage status to `COMPLETE` so round queries return normally.
- Preserve the VL sequence reserve/confirm/release contract: the override acquires the next sequence from `vl_sequence`, and on failure the sequence is released exactly as in the automated path.

**1.11.3 — Tests** (~1 day)

- Unit tests covering both endpoints: auth rejection without the admin key, validation failures (unknown master key, missing reason, invalid `round_id`), concurrency collision with the advisory lock, full success path with mocked downstream clients.
- End-to-end test: against a real devnet deployment, trigger a `custom` publish with the current UNL and a `rollback` publish against an earlier round. Verify the IPFS audit trail directory is written, the on-chain memo uses the override type, and the explorer round-query endpoint returns the synthetic round with the override flag.

**1.11.4 — Documentation** (~0.5 day)

- Extend `docs/ScoringOperations.md` with runbooks for both override scenarios (see the Operations guide updates section of this milestone in `docs/ScoringOperations.md`).
- Add a bullet to `docs/M1.11_ExplorerScoringUI.md`'s status-badge table (if relevant) or note in the audit-trail panel design that override rounds render with a distinct marker.

**1.11.5 — Dry-run exercise on devnet** (~0.5 day)

- Before declaring Phase 1 complete, invoke each endpoint against the devnet deployment at least once with a plausible but non-disruptive payload (custom: the current UNL; rollback: a previous completed round). Confirm the VL is signed and served at `/vl.json`, the audit trail is pinned to IPFS, and the on-chain memo is submitted with the override type.

**Deliverables:**
- Two admin-guarded override endpoints (`publish-unl/custom`, `publish-unl/from-round/{round_id}`) routed through the existing sequence, audit-trail, and memo machinery
- Database schema updated with `override_type` and `override_reason` columns on `scoring_rounds`
- Test coverage including an end-to-end exercise against devnet
- Operational runbooks in `docs/ScoringOperations.md`
- Explicit removal note tying these endpoints to the Phase 3 authority-transfer boundary

---

### Milestone 1.12: Explorer Scoring Pages

**Duration:** ~9-14 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.10.5 (first scoring round producing real data) | **Parallel with:** M1.10.10+

**Design reference:** `docs/M1.11_ExplorerScoringUI.md` — full information architecture, page mockups, state taxonomy, routing, caching, loading/error/empty-state taxonomy, accessibility, mobile, and per-section data-source map. The filename reads `M1.11_` for historical reasons (the scope was renumbered to M1.12 when admin overrides became M1.11); the milestone is M1.12. Read that document before implementation; this milestone section tracks scope and sequencing only.

**Goal:** Give validators and operators a visual way to see scores, reasoning, UNL status, round history, and the verifiable audit trail. Three explorer surfaces are touched: the existing **Validators page**, the existing **validator detail page**, and a new dedicated **UNL Scoring page**. The same UI serves both developers and the public — there is no separate admin surface.

**Steps:**

**1.12.1 — Backend: `/api/scoring/config` endpoint** ✅ (~0.5 day) — **hard dependency for all frontend steps**
- New read-only public endpoint on the scoring service exposing `cadence_hours` (float), `unl_score_cutoff` (int), `unl_max_size` (int), `unl_min_score_gap` (int), sourced from `scoring_service/config.py`
- Required for the Scoring page countdown (A banner), churn-gap chips on the ranked table (B), and the methodology explainer's live values (F) — never hardcoded in the frontend
- No auth. Handler lives in `scoring_service/api/scoring.py` alongside the existing `/rounds`, `/rounds/{id}`, `/unl/current`, `/trigger` handlers (router already has `prefix="/api/scoring"`)
- Tests in `tests/` following the `TestClient` pattern used by `test_status_api.py`
- Ships ahead of frontend work via the existing branch-based deploy workflow

**1.12.2 — Explorer Express proxy + caching layer** ✅ (~1 day) — **hard dependency for all frontend steps**
- Add `/api/scoring/*` proxy routes to `explorer/server/` that forward to `scoring-{env}.postfiat.org`. Browser never calls the scoring service directly (no CORS exposure, consistent with existing `/api/v1/*` pattern)
- Process-wide in-memory stale-while-revalidate cache keyed by URL. Per-endpoint TTLs:
  - `GET /rounds/<N>` (past round): indefinite or 24h (immutable once complete)
  - `GET /rounds?limit=20`: a few minutes
  - `GET /unl/current`: a few minutes
  - `GET /rounds?limit=1`: 15–30s (may flip running → complete mid-round)
  - `GET /config`: 1 hour
- On upstream failure, serve cached (stale) value with response header `X-Scoring-Stale: true` so the UI can surface a "showing cached data" notice
- Cold-start failure (no cache + upstream down) falls through to graceful degrade per the loading/error/empty-state taxonomy in the design spec

**1.12.3 — Backend: move audit-trail router under `/api/scoring` prefix** ✅ (~0.5 day) — **hard dependency for all frontend steps that read per-round artifact files**
- Change the audit-trail router prefix from `""` to `"/api/scoring"` in `scoring_service/api/audit_trail.py` so `GET /rounds/{id}/{file}` becomes `GET /api/scoring/rounds/{id}/{file}`, unifying the scoring service's public API under a single coherent prefix
- After this change, artifact fetches (`scores.json` for the Validators badge, `unl.json`, `snapshot.json`, `vl.json`, `metadata.json` for drill-down and audit-trail panel) all route through the existing `/api/scoring/*` explorer proxy naturally — no proxy-side work needed
- Verify no routing collision with existing `/api/scoring/rounds/{round_id}` handler in `scoring.py` (different segment count: `{round_id}` expects one segment after `rounds/`, `{round_number}/{file_path:path}` expects two or more)
- Update `ScoringOperations.md` and any other docs that reference the old `/rounds/{id}/{file}` path
- Ships via the existing branch-based deploy workflow ahead of frontend work

**1.12.4 — Validators page: replace binary UNL with combined Status badge** ✅ (~0.5-1 day)
- The existing binary UNL column (green checkmark) is replaced by a **single combined Status column**. The badge carries both the numeric score and UNL status as one visual unit: `● 82 on UNL`, `◐ 58 candidate`, `○ 31 ineligible`, `— no data`. One column instead of two so score and status always travel together
- Glyphs (`● ◐ ○ —`) are distinct characters, not CSS-tinted dots — status must be readable without color
- **Data sources** (all through the explorer proxy): VHS remains authoritative for agreement, domains, versions, topology. Scoring-specific data arrives as (1) UNL membership from `GET /api/scoring/unl/current` (on UNL vs candidate vs ineligible/no-data), (2) overall score per validator from `GET /api/scoring/rounds/{id}/scores.json` (reachable post-1.12.3), (3) latest round metadata from `GET /api/scoring/rounds?limit=1`. Merge the three by `master_key` before passing to the table component
- **Fixed best-first row ordering** — rows are sorted by status rank (on-UNL → candidate → ineligible → no-data), then by overall score descending within each status, then by 30-day agreement descending as tie-break. No user-controlled sort: the table presents a single authoritative order and does not expose clickable column headers or direction toggles
- Three Agreement columns (1H / 24H / 30D), Version, Fee Voting fields, and Last Ledger are unchanged
- Freshness footer `Scores from round #N — completed X ago.` escalates color with staleness: neutral (< cadence + 24h), amber (> cadence + 24h), red (> 2× cadence). Cadence from `/api/scoring/config`
- **UNL source switch:** The current explorer derives UNL membership from VHS, which queries the RPC node's admin `validators` command on a 5-minute manifest job interval (up to ~10 min propagation delay after a new VL publishes). Replace with the direct `/api/scoring/unl/current` fetch above for immediate reflection of the latest published UNL. VHS remains authoritative for everything else
- Files: `explorer/src/containers/Network/Validators.tsx` (data fetching + merge), `explorer/src/containers/Network/ValidatorsTable.tsx` (UI)

**1.12.5 — Validator detail page: Scoring section** ✅ (~0.5-1 day)
- Placement: **between the existing agreement-bars overview grid and the tabs.** Match that grid's visual style (reuse `MetricCard` or equivalent); do not invent a new panel type
- Content: status badge, overall score, five dimension sub-scores (Consensus, Reliability, Software, Diversity, Identity) inline
- Each dimension label has a tooltip defining what it measures — more critical here than on the Scoring page because this page can be reached directly via search with no surrounding context
- No-data copy: "This validator wasn't scored in the latest round (#N). Validators appear in rounds automatically once they're active on the network — no registration required." Actionable, not scolding
- Failed-latest-round fallback: falls back to most recent `COMPLETE` round; shows a link with concrete text `round #N+1 failed — see why` that navigates to `/unl-scoring/rounds/N+1`
- Freshness ("X ago") is computed from the same helper as the Scoring page banner so they never drift — one source of truth
- `[ View reasoning and round history → ]` navigates to `/unl-scoring/rounds/<latest>?validator=<pubkey>`, opening the Scoring page with this validator's drill-down auto-expanded
- Reasoning text is intentionally omitted here — it lives on the Scoring page where full round context is available

**1.12.6 — Backend: pipeline-status health endpoint** ✅ (~0.5-1 day) — **hard dependency for the Scoring page banner**
- New read-only public endpoint at `GET /api/scoring/health` returning three signals — `scheduler`, `llm_endpoint`, `publisher_wallet` — each as `{ healthy: bool, detail: string }`, for the Scoring page banner's health strip
- `scheduler`: derived from the DB — healthy if the newest `scoring_rounds.created_at` is within `2 × scoring_cadence_hours`
- `llm_endpoint`: derived from the most recent round — unhealthy only when status is FAILED, `snapshot_hash` is set, and `scores_hash` is null (the "failed at scoring stage" heuristic)
- `publisher_wallet`: `account_info` RPC call against the configured PFTL wallet; healthy if the call returns with balance above a minimum sufficient for several memo transactions. Result cached server-side for ~30 seconds so banner polling does not hammer the RPC node
- Kept **separate** from the existing `/health` endpoint (which is DB-liveness for infra/Docker probes) — different audience, different contract, do not conflate
- Must land before 1.12.7 (banner implementation)

**1.12.7 — Scoring page: header banner + ranked table** ✅ (~1.5-2.5 days)
- New top-level page at `/unl-scoring`, added to the explorer's main navigation **between Validators and Amendments**. Page scaffolding uses the existing `dashboard-panel` visual vocabulary
- **Header banner**, three state variants driven by `scoringRound.status` and `latestAttempt`:
  - **Idle** — three `MetricCard`s: `Last round` showing `#N` with a relative-time subtitle (`formatRelativeTime`), `Next round in` showing remaining countdown with a natural-language cadence subtitle (`formatCadence` — exact words `hourly` / `daily` / `weekly`, mixed-unit `Xh Ym` / `Xd Yh` / `Xw Yd` fallbacks for other values), and `Health` — a three-dot strip (scheduler, LLM endpoint, publisher wallet) driven by `GET /api/scoring/health` from 1.12.6 with each signal's `detail` string populating its tooltip. **No LLM-generated network summary** — the banner stays to operationally-checkable facts
  - **In-progress** — single line `Round #N running — started Xs ago` with the health strip beside it. **No stage-by-stage pipeline breakdown** — rounds complete in minutes; stage breakdown adds complexity without matching v1 value
  - **Failed** — failure stage + error string (expandable behind `[ more ▼ ]` for long traces); reference to the last successful round; direct link `[ View round #N details → ]`; health strip in the footer
- **Countdown semantics:** the `Next round in` countdown transitions past the deadline into a `due Xm ago` form with cadence-proportional color escalation — neutral below 10% of cadence overdue, amber between 10% and 50%, red above 50%. Minute values ceil so the countdown and the `Last round` relative-time subtitle always sum to the configured cadence without losing a sub-minute residual on either side
- **Banner tick:** a `useTicker` hook re-renders the banner on a 30-second interval so relative-time labels and the countdown stay current between react-query refetches; the interval is cleaned up on unmount
- **Ranked table:**
  - Columns: Rank, Validator (verified-domain badge where present, clickable link to the validator detail page), Overall (with inline Δ vs previous round: `↑3`, `↓1`, `=`, `new`, `displaced`), Consensus, Reliability, Software, Diversity, Identity. Row order is fixed best-first (status rank → score desc → 30-day agreement desc) with no user-controllable sort
  - The 5 dimension columns render as horizontal filled bars using the existing `agreement-bar-*` pattern and the `getScoreColor` ramp already defined in `scoringUtils.ts`
  - Dimension column headers carry tooltips from `SCORING_DIMENSIONS` in `scoringUtils.ts` — the same canonical copy introduced by 1.12.5
  - Δ data: `useScoringContext` fetches `/api/scoring/rounds/{N-1}/scores.json` and `/api/scoring/rounds/{N-1}/unl.json` alongside the current round; client-side delta computation by `master_key`. No new backend endpoint
  - Two separator chips on dividers: `CANDIDATE · +{unl_min_score_gap} to displace` and `INELIGIBLE · below {unl_score_cutoff}`, values sourced live from `/api/scoring/config`
  - Churn-gap visualization: candidates above the cutoff but within `weakest_on_UNL + unl_min_score_gap` get a subtle amber outline (above cutoff, still can't displace this round)
  - Filter/search box top-right: debounced client-side filter matching pubkey or domain substring; filtered rows hide but separator chips stay in place
  - Sticky table headers — column labels stay visible when scrolling
  - Empty-zone rendering: single-row placeholder `— No candidates this round —` / `— No ineligible validators this round —` when a zone is empty; if both zones are empty, the table collapses to a single `all on UNL` chip so adjacent horizontal rules never stack
- **Shared primitive:** `MetricCard` gains an optional `subtitle?: ReactNode` prop (additive, non-breaking) so the idle banner's relative-time and cadence subtitles reuse the existing card component instead of introducing a parallel one

**1.12.8 — Scoring page: inline drill-down + sparkline** ✅ (~1-1.5 days)
- Row click on the ranked table (from 1.12.7) expands an inline drill-down beneath the clicked row. The click handler does not change the URL in this step (deep-linking is added in the later routing step)
- **Enrichment** block: Domain (with verification state), ASN, Country, Agreement (30D). **IP is not shown** — publishing validator IPs on a public page is a DDoS-targeting risk; ASN + country provide the diversity signal
- **Score-history sparkline**: new small inline chart primitive (~60px × 20px) rendering this validator's overall score across the last ~10 rounds. Data-fetching strategy: on drill-down open, fire parallel `GET /api/scoring/rounds/{N}/scores.json` calls for the last ~10 round numbers (derived from a `/rounds?limit=10` call) and slice each artifact by `master_key`. The Express proxy cache makes repeat expansions of the same validator or crossover between validators effectively free
- **LLM reasoning** as a single block (upstream LLM output is not structured per-dimension in the current pipeline; keep as one block, revisit if that changes)
- **Two separate download buttons** — `[ Download snapshot entry ]` and `[ Download score entry ]` — each slicing the respective artifact client-side by `master_key`; no new backend endpoints
- `[ Open validator detail page → ]` link for full context
- The sparkline component is extracted to a shared location (`explorer/src/containers/Network/`) so it can be reused on the validator detail page or future scoring surfaces

**1.12.9 — Scoring page: round navigation strip + audit trail panel** ✅ (~1-2 days)
- **Round navigation strip** placed between the header banner and the ranked validator table. Two rows:
  - **Top row:** `◀ Prev` / `Next ▶` arrow controls with the currently-viewed round's meta inline between them (`Round #N  ● COMPLETE  ·  scheduled  ·  completed 4m ago`). Arrows disable at the bounds of the fetched window; `Next ▶` also disables when the nav is already on the latest round.
  - **Bottom row:** compact recent-status strip showing the last 15 rounds as small colored glyphs — green `●` for COMPLETE, red `✕` for FAILED, yellow `●` for non-terminal running states. Hovering a glyph surfaces round number, date, and status via a native `<title>` tooltip; clicking jumps the nav directly to that round. The glyph for the currently-viewed round gets a subtle ring so the reader sees their position in the history at a glance.
  - Initial load: `GET /api/scoring/rounds?limit=15`. Load-more-beyond-15 is out of scope for this milestone — 15 rounds comfortably covers recent-failure-pattern detection on any realistic cadence, and if operators need deeper history later a `[ Load more ]` control can be added without restructuring the strip.
- **Trigger derivation** (no explicit `trigger` field exists on the round record): the strip renders `override` when `override_type` is non-null on the round, and defaults to `scheduled` otherwise. This captures the ~99% case where rounds are either scheduler-triggered or admin-override-triggered; if a distinct `manual` vs `scheduled` classification becomes useful later it requires a backend field addition.
- **Failed-at-stage derivation** (no explicit stage field exists on the round record): for FAILED rounds the stage label surfaced in the tooltip is derived client-side from which of the round's `*_hash` / `*_sequence` / `*_cid` fields are populated — the first missing one in pipeline order (`snapshot_hash` → `scores_hash` → `vl_sequence` → `ipfs_cid` → `github_pages_commit_url` → `memo_tx_hash`) names the stage. Matches the heuristic already used by the pipeline-health endpoint.
- **Navigation state**: clicking an arrow or a strip glyph switches a local `viewingRoundNumber` React state. The ranked validator table and the audit trail panel both re-render for the selected round. The URL does not change in this milestone — URL-driven deep-linking is M1.12.11. When a new round completes in the background (observed via the existing `latestAttempt` refetch on `/api/scoring/rounds?limit=1`), the nav auto-advances to the newer round **only if** the user has not explicitly selected a non-latest round; explicit selections are sticky until the user clicks `Next ▶` back to latest. The header banner (Last round / Next round in / Health cards) stays locked to the actual latest-pipeline-round state regardless of navigation — the banner describes the pipeline, the nav strip describes what the user is looking at.
- **Audit trail panel** placed below the ranked validator table. Surfaces the verification chain for the currently-viewed round:
  - **IPFS CID** with a copy button plus two gateway links named by literal hostname (`Open on ipfs-{env}.postfiat.org`, `Open on Pinata gateway`). Per-environment hostname derived from `VITE_ENVIRONMENT`.
  - **Published VL** block: VL sequence (round number ≠ VL sequence — failed rounds advance the round counter but not the VL counter), effective-from UTC, expires-at UTC with a relative `in X days` suffix, and a per-round `vl.json` download wired to `/api/scoring/rounds/<N>/vl.json` — not the always-latest `/vl.json`, which would serve the wrong blob when viewing a historical round.
  - **On-chain memo** block: tx hash with copy button, ledger index, memo body rendered as raw JSON in a monospace block (faithful to what was submitted on-chain), and a `[ View transaction on explorer → ]` link opening `/transactions/<hash>` in a new tab — consistent with the drill-down's detail-page link, keeps the scoring page available for continued inspection.
  - **GitHub Pages commit URL** (`github_pages_commit_url` on the round record) as a single link.
  - **Artifacts on IPFS** — `snapshot.json · scores.json · unl.json · vl.json · metadata.json` listed as informational; all are pinned to the CID above, content-addressed and tamper-evident. Per-file SHA-256 hashes are not displayed: the CID itself is a content hash, and any tampering changes the CID which then mismatches the on-chain memo — that chain is the verification, not redundant file hashes.
  - **Override rounds** surface `override_reason` as a distinct row in the panel when `override_type` is non-null.
- **Failed-round audit trail** collapses to `No audit trail — round did not publish. See the Round navigation strip for the failure stage, and the Header banner for the error message.` The panel stays rendered so the layout doesn't shift, only its content substitutes this placeholder for the verification chain.

**1.12.10 — Scoring page: methodology explainer** ✅ (~0.5 day)
- **Two collapsible accordions** (not four): `How scoring works` and `How to verify`
- Per-dimension definitions (what Consensus vs Reliability etc. actually measure) are **not** a top-level accordion item — they live as tooltips on the dimension column headers in the ranked table, where users are actually looking at dimension values
- Live values (`cutoff`, `max_size`, `min_gap`, `cadence_hours`) rendered from `/api/scoring/config`; never hardcoded
- Do not link to `docs/Design.md` in the repo from the UI; inline the relevant content

**1.12.11 — Routing + deep-link support** ✅ (~0.5 day)
- Routes:
  - `/unl-scoring` → latest completed round, auto-advances when a new round completes
  - `/unl-scoring/rounds/:roundId` → specific historical round, pinned (suppresses auto-advance)
  - `?validator=<pubkey>` (comma-separated list, supported on both routes) → auto-expand those validators' drill-downs; the first known pubkey in URL order is scrolled into view
- Round navigation pushes browser history (Back steps through rounds); drill-down toggles replace the current entry (Back skips expand/collapse noise)
- Invalid `:roundId` renders a not-found panel on the page without redirecting the URL; unknown validator pubkeys are silently ignored at render time but preserved in the URL so they survive round navigation to a round where they do exist
- react-router v6 (already in use); primary ops use case is pasting a shareable link into Slack or a commit message

**1.12.12 — Loading, error, genesis states** ✅ (~0.5-1 day)
- Loading: skeleton rows / shimmer (reuse the existing `src/containers/shared/components/Skeleton` primitive); never show `— no data` during load
- Score-history sparkline prefetch: warm the `useScoreHistory` cache at the UNL Scoring page level so the batch fetch (`/rounds?limit=10` + per-round `scores.json` / `unl.json` artifacts) starts as soon as the page mounts; by the time an operator opens the first drill-down the sparkline is already populated instead of shimmering for ~1 second
- Genesis (no completed rounds ever on this network): hide Scoring nav link, hide Status column on Validators page, hide Scoring section on validator detail page. Direct `/unl-scoring` hit: "No scoring rounds have completed on this network yet." Auto-detected from `GET /rounds?limit=1` empty result — no env flag; feature appears automatically when the first round completes. Surfaced through a single `useScoringAvailability()` hook consumed by the sidebar, Validators page, validator detail page, and UNL Scoring page
- Transient error with cached data: serve cached + subtle "showing cached data — scoring service unreachable" banner on the UNL Scoring page only (Validators page and validator detail page do not show the banner to avoid noise), driven by an axios response interceptor that flips a shared "scoring is stale" flag whenever any `/api/scoring/*` response carries `X-Scoring-Stale: true`
- Transient error no cache: Scoring page shows a retry message with an explicit Retry button (spinner while refetching); other pages hide affected columns with a small inline notice
- Config endpoint failure: banner countdown shows `—`, methodology prose shows without live values (no hardcoded fallbacks)

**1.12.13 — Accessibility + mobile** (~1 day)
- Status states use distinct glyphs (`● ◐ ○ —`), not color alone; glyphs render as actual characters
- Interactive elements keyboard-accessible with visible focus rings; color contrast WCAG AA on bars and badges
- Mobile: ranked table's 5 dimension columns collapse into a single `Details ▼` cell that expands inline on tap; Rank, Validator, Overall, Δ, Details remain visible
- Validators page three Agreement columns may collapse per existing responsive rules; Validator detail Scoring section stacks to single column
- Mobile layout verified on devnet before deploy, not deferred to polish

**1.12.14 — Polish + deploy** (~0.5-1 day)
- Reuse audit: confirm `MetricCard`, `StatusBadge`, `CopyableAddress`, `getAgreementColor`, `dashboard-panel` used where applicable; name any genuinely new shared primitive (e.g., sparkline) and place it in a shared location
- Deploy to devnet explorer instance; verify data updates after a new scoring round completes
- Verify proxy cache behavior under scoring-service downtime (kill upstream, confirm stale data served with header)

**Deliverables:**
- New `/api/scoring/config` endpoint on the scoring service (step 1.12.1)
- Audit-trail router moved under `/api/scoring` prefix — artifact files now reachable through the explorer proxy alongside the rest of the scoring API (step 1.12.3)
- New pipeline-status health endpoint on the scoring service — separate from the infra `/health` — driving the banner's health strip (step 1.12.6)
- Explorer Express proxy at `/api/scoring/*` with stale-while-revalidate in-memory cache (per-endpoint TTLs)
- Combined Status badge column on the Validators page (replacing the binary UNL column); fixed best-first row order with staleness-escalating freshness footer
- Scoring section on the validator detail page with per-dimension tooltips, rewritten no-data copy, and concrete failed-round link
- New UNL Scoring page: three-state header banner with health strip (no LLM network summary, simplified in-progress variant); ranked table with Δ column, dimension bars, two labelled separator chips, churn-gap visualization, filter/search, sticky headers, expandable drill-down with sparkline (no IP), round navigation strip with prev/next arrows, current-round meta line, and recent-15-round status strip (clickable glyphs with derived failure-stage tooltips), audit trail panel (named gateways, per-round VL, VL sequence + expiration, no SHA display), two-accordion methodology explainer
- Routing: `/unl-scoring`, `/unl-scoring/rounds/:roundId`, `?validator=<pubkey>` deep-linking
- Loading / genesis / transient-error state handling across all three surfaces
- Accessibility (non-color-dependent status signaling, WCAG AA contrast, keyboard navigation) and mobile layout (expandable dimension cell, verified on devnet)
- Deployed to devnet explorer

---

### Milestone 1.13: Testnet Deployment

**Duration:** ~3-5 weeks elapsed (of which ~4-6 days active engineering, the rest observation) | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.10, 1.11

**Goal:** Deploy the scoring pipeline to testnet and transition ~30 validators (5 foundation-operated, ~35 community-operated) to the dynamically generated VL without requiring any community validator to change their configuration.

**Publisher-key continuity:** Testnet validators' `validators-testnet.txt` already points at `https://postfiat.org/testnet_vl.json` signed by publisher key `ED3F1E0DA736FCF99BE2880A60DBD470715C0E04DD793FB862236B070571FC09E2`. The scoring service reuses this exact master key and signing manifest, so the transition is a URL-content overwrite, not a trust-root rotation. Community validators need no config change, no restart, and no coordination. This removes the only meaningful source of operator friction from the transition. (Custody: the key is held by the foundation's blockchain engineer and a second principal; neither holder should ship the key onto any system outside the scoring service's secret store, and the previous publishing location should cease signing once parity is confirmed.)

**Steps:**

**1.13.1 — Testnet observation window (dry-run only)** (~2-3 weeks elapsed, ~1 day active)

- Deploy the scoring service to testnet via the existing `deploy-testnet.yml` workflow with the scheduler running in dry-run mode. In dry-run, the orchestrator progresses through `COLLECTING → SCORED → SELECTED → DRY_RUN_COMPLETE` and stops before VL signing.
- Let the service run for 2-3 weekly dry-run rounds against the real testnet validator set.
- For each dry-run round, inspect the proposed UNL via `/api/scoring/rounds/{N}` and the explorer's UNL Scoring page (M1.12). Review:
  - Are scores differentiated across the full testnet validator set?
  - Does the proposed UNL share high overlap with the current static UNL? If not, understand why (the LLM may be correctly penalizing a validator that merits it — treat this as new information, not a bug).
  - Is the prompt handling ~40 validators within the context window?
  - Is scoring deterministic across repeated `replay_round` invocations on the same snapshot?
- Community communication during this window: post a Forum/Telegram notice that dry-run observation has begun, link the explorer's Scoring page, and commit to a go-live date at the end of the observation window.

**1.13.2 — Go-live gating review** (~0.5 day)

- Go-live criteria (all must hold):
  - At least 2 consecutive dry-run rounds complete without failure.
  - Proposed UNL in the most recent dry-run matches, or is well-justified against, operator expectations.
  - Admin override endpoints (M1.11) have been dry-run exercised against testnet.
  - Community notice has been posted at least 72 hours before go-live.
- If any criterion fails, extend observation and iterate on the prompt or data pipeline.

**1.13.3 — First live scoring round with extended lookahead** (~1 day)

- Trigger the first live round via `POST /api/scoring/trigger` with `effective_lookahead_hours=24` (exposed as a request parameter for admin callers, or invoked via the custom admin endpoint if simpler) so the resulting VL is signed with `effective = now + 24 hours`.
- Scoring service writes the signed VL to `https://postfiat.org/testnet_vl.json` (see 1.13.4 for the mechanism). Every validator picks up the pending blob within the default 5-minute poll interval; the blob is held in `remaining` until `closeTime >= effective`, at which point all validators activate simultaneously.
- During the 24-hour window, inspect the VL contents, the audit trail, and the on-chain memo. If anything is wrong, invoke the rollback admin endpoint (M1.11) to republish the previous UNL with a higher sequence and a shorter effective time. Because the first-round blob is still pending, the rollback blob with `effective = now + short-lookahead < 24h` will supersede it cleanly.

**1.13.4 — Content delivery to the existing VL URL** (~0.5 day)

- Option A is the chosen transition mechanism: the scoring service's signed VL overwrites the content at `https://postfiat.org/testnet_vl.json` via the Pages publisher built in M1.10.7. Configure the testnet deployment of the scoring service with `GITHUB_PAGES_FILE_PATH=testnet_vl.json`, `GITHUB_PAGES_REPO=postfiatorg/postfiatorg.github.io`, and a dedicated `TESTNET_GITHUB_PAGES_TOKEN` (separate PAT from devnet — same service account, separate secret for least-privilege cross-environment isolation).
- GitHub Pages atomicity: the Contents API replaces the file in a single commit, and the Pages build serves either the previous commit or the new commit, never a partially-written file.
- The scoring service continues to also serve its own copy at `https://scoring-testnet.postfiat.org/vl.json` for tooling that prefers the scoring-native domain. Validators do not consume this endpoint; they consume `postfiat.org/testnet_vl.json` exclusively.

**1.13.5 — Monitoring and stabilization** (~1-2 weeks elapsed, ~1-2 days active)

- Run 2-3 weekly scoring rounds post-go-live with the default 1-hour `effective_lookahead_hours`.
- Monitor:
  - Consensus stability on testnet via VHS agreement scores and the network-monitoring dashboard.
  - VL acceptance rate across the community validator set (VHS exposes this indirectly through agreement data).
  - Any community validator complaints or observed divergence.
- Address any issues that arise; use admin override endpoints for any manual intervention.

**Deliverables:**
- Scoring pipeline running on testnet
- All testnet validators consuming the dynamically generated VL via the existing `postfiat.org/testnet_vl.json` URL (no operator config change required)
- At least 2 successful weekly scoring rounds completed post-go-live
- Admin override endpoints exercised at least once against testnet in a non-production-impacting manner
- No consensus disruptions attributable to the transition

---

### Phase 1 Decision Gate

**Criteria for proceeding to Phase 2:**

| Criterion | Required | Status |
|---|---|---|
| Scoring pipeline running stable on testnet for 2+ weeks | Yes | |
| All testnet validators consuming dynamic VL | Yes | |
| No consensus disruptions from VL transitions | Yes | |
| Scoring quality reviewed and acceptable | Yes | |
| Audit trail published to IPFS and verifiable | Yes | |
| On-chain memo publication working | Yes | |
| Effective-timestamp lookahead mechanism in use on both devnet and testnet | Yes | |
| GitHub Pages publisher pushing VLs to `postfiatorg/postfiatorg.github.io` for both devnet (`devnet_vl.json`) and testnet (`testnet_vl.json`) deployments | Yes | |
| Admin override endpoints (custom and from-round) exercised end-to-end against a non-production deployment | Yes | |
| Determinism research complete (Milestone 0.3) | Yes | |
| Reproducibility harness built and run — >99% output equality on mandatory GPU type | Yes | |
| Mandatory GPU type selected for Phase 2 | Yes | |

---

### Operational Safety Notes (Phase 1)

The Phase 1 rollout relies on properties of postfiatd's existing validator-list consumption path that are not always obvious to readers of this roadmap. These notes capture the load-bearing ones so future operators and reviewers understand why specific parameters are set where they are.

**VL polling is HTTP-only and independent of consensus events.** `ValidatorSite::onTimer` schedules refresh fetches on a per-site `boost::asio` timer with a default interval of 5 minutes (clamped between 1 minute and 1 day, optionally overridden per-response by a `refreshInterval` field). Flag ledgers (every 256 ledgers) are used for amendment and fee voting only — `isFlagLedger` is never referenced by VL code. No postfiatd C++ change, no amendment, and no on-chain event is required for validators to begin consuming the scoring service's VLs.

**VL activation is synchronized via the `effective` field, not the fetch time.** When a v2 blob carries `effective > closeTime`, postfiatd holds it in `remaining` and promotes it to `current` only when `closeTime >= effective`. Publishing with a lookahead (see M1.10.6) allows every validator to fetch the pending blob in advance and transition in unison on the same ledger close. This is why the M1.13 first-live round uses 24 hours of lookahead (human-review headroom) while automated rounds use 1 hour (comfortably greater than the 5-minute poll interval without delaying applied UNL changes unnecessarily).

**An expired VL does not silently fall back to `[validators]`.** When the current VL's `validUntil` has passed and no new blob has arrived, postfiatd calls `setUNLBlocked()` and halts consensus, serving `warnRPC_EXPIRED_VALIDATOR_LIST` on RPC responses. The local `[validators]` list, if present, is additive rather than a fallback — trust requires `keyListings_[key] >= listThreshold_`. This is why the 500-day default `VL_EXPIRATION_DAYS` is a safety feature: it gives the scoring service a very large margin to recover from any outage before consensus is affected. Shortening it is not advised without a proportionally stronger availability guarantee for the scoring service.

**An unknown publisher key is rejected silently.** When a blob's publisher master key is not in a validator's configured `[validator_list_keys]`, postfiatd returns `untrusted` from `verify` without even checking the signature. There is no loud error. This is why publisher-key continuity is load-bearing for the testnet transition: rotating to a new key without first coordinating with every community operator would cause their validators to silently ignore subsequent VLs. Any future key rotation must use the multi-publisher mechanism (two keys in `[validator_list_keys]`, two blobs signed in parallel) with a long overlap window.

**Round-to-round UNL overlap is protected by churn control, not by the transition mechanism.** The XRPL pairwise-overlap safety bound derives from the 80% quorum requirement: for two validators with UNLs of size `n` and quorum `q = 0.8n` to simultaneously validate conflicting ledgers, some shared validators must vote for both (Byzantine behavior). Pigeonhole analysis yields a theoretical floor on overlap somewhat below 70% for symmetric UNLs with tolerable Byzantine faults; the XRPL operational convention is ≥90% for safety margin against transient Byzantine, offline, and partition conditions. With lookahead, all validators flip UNL simultaneously, so pairwise-overlap-between-validators stays at ~100% during transitions; the overlap concern reduces to round-to-round UNL content change, which `UNL_MIN_SCORE_GAP` (default 5) and incumbent stickiness in `unl_selector.py` keep well above 90% under normal scoring variance.

**GitHub Pages propagation is fast enough for the default lookahead window.** Pages builds typically complete within 1-2 minutes of the Contents API commit. Because automated rounds publish with 1 hour of effective lookahead, validators have ~58 minutes of margin to poll and cache the pending blob before activation — well within the 5-minute default `refreshInterval`. The `VL_DISTRIBUTED` stage does not complete until the Contents API PUT returns successfully; transient 5xx or rate-limit failures are retried with exponential backoff, and persistent failure fails the round before any on-chain memo is spent. The `postfiat-scoring-bot` fine-grained PAT expires annually and must be rotated; rotation procedure is documented in `docs/ScoringOperations.md`.

---

## Phase 2: Validator Verification

**Duration:** ~6-8 weeks | **Difficulty:** ★★★★★ Very Hard

**Goal:** Validators run the scoring model locally on GPU sidecars, publish output hashes via commit-reveal, and verify convergence with the foundation's results. The foundation's UNL remains authoritative — this is shadow mode verification.

```
         M 2.1                 M 2.2               M 2.3
         Commit-Reveal         Sidecar Repo        Sidecar Inference
         Protocol Design       Setup               Engine
         ~2-3 days             ~1-2 days            ~7-10 days
              │                     │                    │
              └─────────┬───────────┘                    │
                        │                                │
                        ▼                                │
                   M 2.4                                 │
                   Sidecar Chain        ◄────────────────┘
                   Integration
                   ~5-7 days
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
         M 2.5     M 2.6     M 2.7
         Converg.  Validator  postfiatd
         Monitor   Onboard   Changes
         ~5-7 days ~1-2 days ~5-7 days
              │         │         │
              └─────────┼─────────┘
                        ▼
                   M 2.8
                   Devnet Testing
                   ~5-7 days
                        │
                        ▼
                   M 2.9
                   Testnet Rollout
                   ~5-7 days
```

---

### Milestone 2.1: Commit-Reveal Memo Protocol Design

**Duration:** ~2-3 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Phase 1 complete

**Goal:** Define the exact on-chain memo formats and timing protocol for validator commit-reveal scoring rounds.

**Steps:**

**2.1.1 — Define memo types** (1 day)

Four new memo types for the commit-reveal protocol:

**Round Announcement** (published by foundation):
```json
{
  "type": "pf_scoring_round_v1",
  "round_number": 42,
  "snapshot_ipfs_cid": "Qm...",
  "snapshot_hash": "<sha256 of snapshot.json>",
  "model_version": "Qwen2.5-32B-Instruct",
  "model_weight_hash": "sha256:abc123...",
  "prompt_version": "v1.0.0",
  "commit_deadline_ledger": 50000,
  "reveal_deadline_ledger": 50500,
  "published_at": "2026-06-01T00:00:00Z"
}
```

**Commit** (published by each validator's sidecar):
```json
{
  "type": "pf_scoring_commit_v1",
  "round_number": 42,
  "validator_public_key": "nHUDXa2b...",
  "commit_hash": "<domain-separated hash — see 2.1.4>"
}
```

**Reveal** (published by each validator's sidecar after commit window closes):
```json
{
  "type": "pf_scoring_reveal_v1",
  "round_number": 42,
  "validator_public_key": "nHUDXa2b...",
  "scores_ipfs_cid": "Qm...<CID of scored output>",
  "salt": "<random 32-byte hex>",
  "scores_hash": "<sha256 of scores JSON>"
}
```

**Convergence Report** (published by foundation after reveal window closes):
```json
{
  "type": "pf_scoring_convergence_v1",
  "round_number": 42,
  "total_validators": 30,
  "commits_received": 28,
  "reveals_received": 27,
  "converged": true,
  "convergence_rate": 0.96,
  "divergent_validators": ["nHxyz..."],
  "report_ipfs_cid": "Qm..."
}
```

**2.1.2 — Define timing protocol** (0.5-1 day)

```
Round Lifecycle (Phase 2)

  T+0h              T+1h              T+7h              T+8h         T+9h
  │                 │                 │                 │            │
  ▼                 ▼                 ▼                 ▼            ▼
  ┌─────────────────┬─────────────────┬─────────────────┬────────────┐
  │  Round          │  Inference      │  Commit         │  Reveal    │
  │  Announcement   │  Window         │  Window         │  Window    │
  │  (foundation    │  (validators    │  (validators    │  (publish  │
  │   publishes     │   run model,    │   submit hash   │   scores   │
  │   snapshot)     │   produce       │   on-chain)     │   to IPFS) │
  │                 │   scores)       │                 │            │
  └─────────────────┴─────────────────┴─────────────────┴────────────┘
                                                                    │
                                                                    ▼
                                                              ┌───────────┐
                                                              │Convergence│
                                                              │Check +    │
                                                              │Report     │
                                                              │(T+9-10h)  │
                                                              └───────────┘
```

- Timing uses ledger indices (deterministic, not wall-clock) as deadlines
- Approximate ledger close time: ~4 seconds on PFTL
- Commit window: ~1500 ledgers (~6 hours) — enough for cold starts + inference
- Reveal window: ~250 ledgers (~1 hour)
- Convergence check: after reveal window closes

**2.1.3 — Domain-separated hash construction** (0.5 day)
- Define a canonical binary encoding for all hash preimages — never use loose string concatenation
- Commit hash format: `sha256(domain_tag || version_uint8 || round_uint64 || scores_hash_32bytes || salt_32bytes)`
- `domain_tag` is a fixed-length string identifying the hash purpose (e.g., `"pf_scoring_commit_v1\x00"`)
- Fixed-width fields prevent ambiguity (e.g., `"score12" + "3"` vs `"score1" + "23"`)
- Document the exact binary layout for every hash used in the protocol (commit, reveal verification, convergence)

**2.1.4 — Protocol edge cases** (0.5 day)
- What if a validator commits but doesn't reveal? → counted as non-participant for that round
- What if a validator reveals before commit window closes? → reveal ignored, must wait
- What if fewer than N validators commit? → round still valid (Phase 2 is shadow mode, not binding)
- What if the foundation's round announcement is missed? → no round occurs, previous UNL continues
- How do validators discover the round announcement? → watch for `pf_scoring_round_v1` memos from the foundation's known address
- What if a validator's sidecar wallet doesn't have enough PFT for transaction fees? → sidecar logs error, skips round

**2.1.5 — Participation fallback rules** (0.5 day)
- Define minimum participation thresholds:
  - Minimum validators required for a valid convergence check (e.g., 5)
  - If fewer than the minimum commit, the round is valid but convergence is not assessed
  - Foundation's UNL remains authoritative until participation consistently exceeds threshold
- Fallback behavior:
  - If participation drops below threshold for N consecutive rounds → revert to foundation-only UNL (Phase 1 mode)
  - Foundation-only mode continues until participation recovers
  - No validator rewards (XRPL model) — participation is voluntary, so fallback rules are the safety net
- Document round cadence impact on operator burden (weekly rounds = low burden, daily = high burden)

**Deliverables:**
- Protocol specification document with all memo formats
- Timing diagram with ledger-based deadlines
- Edge case handling documented
- Participation fallback rules documented

---

### Milestone 2.2: GPU Sidecar Repository Setup

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestone 2.1

**Goal:** Create the `validator-scoring-sidecar` repository.

**Steps:**

**2.2.1 — Create repository** (1 hour)
- Create `validator-scoring-sidecar` under `postfiatorg` GitHub org

**2.2.2 — Project structure** (2-4 hours)
```
validator-scoring-sidecar/
├── sidecar/
│   ├── main.py                    # Entry point
│   ├── config.py                  # Configuration (env vars)
│   ├── chain_watcher.py           # Watch for round announcements
│   ├── inference_engine.py        # Load model, run scoring
│   ├── commit_reveal.py           # Submit commit/reveal txs
│   ├── ipfs_client.py             # Publish scores to IPFS
│   └── pftl_client.py             # XRPL transaction client
├── scripts/
│   ├── install.sh                 # One-command setup script
│   ├── check_gpu.py               # Verify GPU compatibility
│   └── download_model.py          # Download + verify model weights
├── modal/
│   ├── deploy_endpoint.py         # Modal serverless deployment (for cloud GPU option)
│   └── Dockerfile                 # Modal template
├── tests/
├── Dockerfile
├── docker-compose.yml
├── env.example
├── requirements.txt
└── README.md                      # Setup guide for validators
```

**2.2.3 — Configuration** (1-2 hours)
```
# Chain connection
PFTL_RPC_URL           # Validator's RPC endpoint (usually localhost)
SIDECAR_WALLET_SECRET  # Funded wallet for commit/reveal transactions
VALIDATOR_PUBLIC_KEY    # This validator's master public key

# Foundation
FOUNDATION_ADDRESS     # Address to watch for round announcements

# Model
MODEL_ID               # HuggingFace model ID
MODEL_WEIGHT_HASH      # Expected SHA-256 of weight file

# IPFS
IPFS_API_URL, IPFS_API_USERNAME, IPFS_API_PASSWORD

# GPU (local mode)
GPU_DEVICE             # CUDA device ID (default: 0)
INFERENCE_BACKEND      # sglang (default)

# Modal (cloud GPU mode, alternative to local)
MODAL_ENDPOINT_URL
```

**Deliverables:**
- Repository with project skeleton
- Configuration documented
- Two execution modes defined: local GPU and Modal cloud GPU

---

### Milestone 2.3: Sidecar Inference Engine

**Duration:** ~7-10 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestone 2.2

**Goal:** Build the inference engine that loads the pinned model and produces scoring output identical to the foundation's pipeline.

**Steps:**

**2.3.1 — Model download and verification** (2-3 days)
- Implement `download_model.py` script:
  - Downloads model from HuggingFace using pinned snapshot revision (safetensors format)
  - Computes SHA-256 of every file in the snapshot (weights, tokenizer, config)
  - Verifies against the full execution manifest from config
  - Stores weights in a persistent local directory (so they survive container restarts)
- Handle: partial downloads (resume), corrupt files (re-download), disk space checks
- The model download only happens once (or when the model version changes)

**2.3.2 — Local inference with SGLang** (3-4 days)
- Implement `InferenceEngine` class with two backends:
  - **Local GPU mode**: loads model into GPU memory using SGLang with `--enable-deterministic-inference`, runs inference locally
  - **Modal cloud mode**: calls Modal serverless endpoint (SGLang backend, same as foundation's pipeline)
- Both modes must produce identical output given identical input + settings:
  - Temperature 0, greedy decoding
  - Same max tokens
  - Same JSON output format
  - Same prompt template (raw prompt strings, not chat-template defaults)
- The local GPU mode uses the deterministic inference settings validated by the reproducibility harness (Milestone 0.3)

**2.3.3 — Prompt template synchronization** (1-2 days)
- The sidecar must use the exact same prompt template as the foundation's scoring service
- Approach: the prompt template version is included in the round announcement memo
- The sidecar fetches the prompt template from a known location (GitHub raw URL, or bundled with the sidecar version)
- If the prompt version in the round announcement doesn't match the sidecar's bundled version: skip the round, log a warning (operator needs to update sidecar)

**2.3.4 — GPU compatibility check** (1 day)
- Implement `check_gpu.py`:
  - Detects installed GPU(s) via `nvidia-smi`
  - Checks if the GPU matches the mandatory type (from Phase 0 research)
  - Checks VRAM capacity vs model requirements
  - Checks CUDA version and driver version
  - Clear pass/fail output with actionable messages
- This runs as part of the install script and on sidecar startup

**Deliverables:**
- Model download + verification script
- Inference engine with local GPU and Modal cloud backends
- GPU compatibility checker
- Prompt template synchronization mechanism

---

### Milestone 2.4: Sidecar Chain Integration

**Duration:** ~5-7 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestones 2.1, 2.3

**Goal:** Build the chain watcher and commit-reveal transaction submission.

**Steps:**

**2.4.1 — Chain watcher** (2-3 days)
- Implement `ChainWatcher` class:
  - Connects to the local PFTL node's WebSocket (or polls RPC)
  - Watches for `pf_scoring_round_v1` memo transactions from the foundation's address
  - When a round announcement is detected: extract snapshot CID, model version, deadlines
  - Trigger the scoring pipeline
- Must handle: node restarts, connection drops, reconnection, missed transactions (backfill from last known ledger)

**2.4.2 — Scoring pipeline integration** (1-2 days)
- When a round is detected:
  1. Fetch snapshot from IPFS by CID
  2. Verify snapshot hash against on-chain hash
  3. Run inference (local GPU or Modal)
  4. Produce scored output JSON
  5. Generate salt (32 random bytes)
  6. Compute commit hash: `sha256(scores_json + salt + round_number)`
  7. Wait for commit window to open

**2.4.3 — Commit transaction** (1-2 days)
- Submit `pf_scoring_commit_v1` memo transaction:
  - Payment of 1 drop from sidecar wallet to memo destination
  - Memo contains commit hash and round number
  - Must be submitted before commit deadline ledger
- Handle: insufficient balance (log error, skip round), transaction failure (retry once)

**2.4.4 — Reveal transaction** (1-2 days)
- After commit deadline passes:
  1. Publish scored output to IPFS
  2. Submit `pf_scoring_reveal_v1` memo transaction with IPFS CID and salt
  3. Must be submitted before reveal deadline ledger
- Verify own commit was included before revealing (read back from chain)

**Deliverables:**
- `ChainWatcher` with round announcement detection
- Full commit-reveal flow: detect round → score → commit → reveal
- Transaction submission with error handling

---

### Milestone 2.5: Convergence Monitoring

**Duration:** ~5-7 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 2.4

**Goal:** Build the convergence checking system in the foundation's scoring service. After each round's reveal window closes, compare all validator outputs to the foundation's output.

**Steps:**

**2.5.1 — Reveal aggregator** (2-3 days)
- Add to the `dynamic-unl-scoring` service:
  - After the reveal deadline: scan chain for all `pf_scoring_reveal_v1` memos for this round
  - For each reveal: verify commit hash matches (sha256(scores + salt + round) == commit hash)
  - Fetch each validator's scored output from IPFS by CID
  - Compare each validator's output hash to the foundation's output hash

**2.5.2 — Convergence analysis** (1-2 days)
- Compare outputs at three levels:
  - **Exact match**: validator's output hash == foundation's output hash → converged
  - **Score-level match**: individual validator scores match within tolerance (e.g., ±2 points) → partially converged
  - **UNL-level match**: the final UNL inclusion list is identical → functionally converged
- For divergent validators, perform **environment diff**: compare the validator's execution manifest against the foundation's to identify which configuration field differs (SGLang version, CUDA driver, model hash, attention backend, etc.). This is the first diagnostic step — most divergence is caused by config mismatch, not cheating.
- Generate convergence report:
  ```json
  {
    "round_number": 42,
    "foundation_output_hash": "abc123...",
    "validators": [
      {
        "public_key": "nHUDXa2b...",
        "committed": true,
        "revealed": true,
        "output_hash": "abc123...",
        "exact_match": true,
        "unl_match": true,
        "score_divergence": 0,
        "manifest_diff": null
      }
    ],
    "convergence_rate": 0.96,
    "unl_convergence_rate": 1.0
  }
  ```

**2.5.3 — Convergence publication** (1-2 days)
- Publish convergence report to IPFS
- Submit `pf_scoring_convergence_v1` memo transaction on-chain
- Add convergence dashboard endpoint to the scoring service API:
  - `GET /api/convergence/rounds` — convergence history
  - `GET /api/convergence/rounds/<id>` — detailed convergence for a round
  - `GET /api/convergence/validators/<key>` — convergence history per validator

**Deliverables:**
- Reveal aggregation and verification
- Convergence analysis (exact, score-level, UNL-level) with environment diff for divergent validators
- Convergence report publication (IPFS + on-chain)
- Convergence monitoring API endpoints

---

### Milestone 2.6: Validator Onboarding Documentation & ChatGPT Agent

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestones 2.3, 2.4

**Goal:** Create comprehensive setup documentation and a ChatGPT agent that guides validators through GPU sidecar installation.

**Steps:**

**2.6.1 — Setup documentation** (0.5-1 day)
- Write a complete setup guide in the `validator-scoring-sidecar` README:
  - **Prerequisites**: existing running validator, funded sidecar wallet (provide faucet instructions for testnet), IPFS access
  - **Option A — Local GPU**: GPU requirements (mandatory type), NVIDIA driver install, CUDA install, Docker with NVIDIA runtime
  - **Option B — Modal Cloud GPU**: Modal account setup, serverless endpoint deployment (step-by-step with screenshots), API key configuration
  - **Installation**: one-command install script walkthrough
  - **Configuration**: every env variable explained with examples
  - **Verification**: how to verify the sidecar is working (check GPU, run test inference, simulate a round)
  - **Troubleshooting**: common errors and solutions
  - **Updating**: how to update when model version changes

**2.6.2 — One-command install script** (0.5 day)
- `install.sh` that:
  1. Checks OS (Ubuntu 24.04+)
  2. Checks Docker installed (installs if not)
  3. Checks NVIDIA driver and CUDA (for local GPU mode)
  4. Runs GPU compatibility check
  5. Downloads model weights (with SHA-256 verification)
  6. Creates `.env` from template (prompts for required values)
  7. Starts the sidecar via Docker Compose
  8. Runs a health check
  9. Prints success message with next steps
- For Modal mode: skips GPU/CUDA checks, prompts for Modal credentials instead

**2.6.3 — ChatGPT agent** (0.5 day)
- Create a custom GPT (similar to the existing validator install agent at the existing ChatGPT link)
- The agent should:
  - Guide users through the entire sidecar setup process step by step
  - Answer questions about GPU requirements, costs, Modal setup
  - Help troubleshoot common installation issues
  - Explain what the sidecar does and why it's needed
  - Reference the official documentation
- Configure with:
  - Full README content as knowledge base
  - Common troubleshooting scenarios
  - FAQ about Dynamic UNL, scoring, and verification
- Publish and share the link with validators

**2.6.4 — Announcement preparation** (1-2 hours)
- Draft Discord/Telegram announcement:
  - What Dynamic UNL is and why it matters
  - What validators need to do (install GPU sidecar)
  - Two options: local GPU or Modal cloud
  - Link to documentation and ChatGPT agent
  - Timeline for Phase 2 activation on testnet
  - FAQ section

**Deliverables:**
- Complete setup documentation in README
- One-command install script
- Custom ChatGPT agent for validator support
- Discord/Telegram announcement draft

---

### Milestone 2.7: postfiatd Changes (if needed)

**Duration:** ~5-7 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Phase 1 complete, Milestone 2.1

**Goal:** Evaluate whether postfiatd needs any C++ changes for Phase 2 and implement them if so.

**Assessment:** Phase 2 may work entirely without postfiatd changes. The sidecar handles chain watching and transaction submission independently. However, evaluate:

**Steps:**

**2.7.1 — Evaluate necessity** (1 day)
- Can the sidecar discover round announcements by watching memo transactions via RPC? → Yes, using `account_tx` or `subscribe`
- Can the sidecar submit commit/reveal as memo transactions via RPC? → Yes, using `submit`
- Does postfiatd need to understand the commit-reveal protocol? → Not in Phase 2 (shadow mode — foundation UNL is still authoritative)
- Does the convergence check need to happen inside postfiatd? → Not in Phase 2 (runs in the scoring service)

**2.7.2 — Optional: Add RPC convenience methods** (3-5 days, only if needed)
- If raw memo watching proves too fragile or slow, consider adding RPC methods to postfiatd:
  - `dynamic_unl_info` — returns current dynamic UNL status (latest round, convergence)
  - `dynamic_unl_rounds` — returns recent scoring round history
- These would read from on-chain memo data and present it in a structured format
- This is optional and can be deferred if the sidecar's chain watching works well

**2.7.3 — Prepare featureDynamicUNL amendment** (2-3 days)
- Add `featureDynamicUNL` to `features.macro` (disabled by default)
- This amendment will gate Phase 3 changes (when the converged validator UNL becomes authoritative)
- For Phase 2, the amendment is defined but not activated
- Validators can vote on it in advance so it's ready for Phase 3

**Deliverables:**
- Assessment document: what postfiatd changes are needed vs not
- `featureDynamicUNL` amendment defined (disabled)
- Optional: RPC convenience methods

---

### Milestone 2.8: Devnet Testing

**Duration:** ~5-7 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 2.4, 2.5, 2.7

**Goal:** Run the full Phase 2 system on devnet with 4 validators.

**Steps:**

**2.8.1 — Deploy sidecars to devnet validators** (1-2 days)
- Install the sidecar on all 4 devnet validators (foundation-controlled)
- Configure each with its own sidecar wallet (funded)
- **At least 2 of 4 validators must use independent execution environments** (separate Modal endpoints or local GPU) — not a shared endpoint. If all validators hit the same endpoint, the test proves transport symmetry, not independent execution.
- The remaining 2 can share a Modal endpoint for comparison
- Start sidecars and verify they're watching for round announcements

**2.8.2 — Run first commit-reveal round** (1-2 days)
- Trigger a scoring round from the foundation scoring service
- Monitor: do all 4 sidecars detect the round announcement?
- Monitor: do all 4 sidecars run inference and produce scores?
- Monitor: do all 4 sidecars submit commit transactions before deadline?
- Monitor: do all 4 sidecars submit reveal transactions after commit window?
- Monitor: does the convergence check produce a valid report?

**2.8.3 — Convergence analysis** (1-2 days)
- Compare output hashes across all 4 validators + foundation
- Critical test: do validators on independent endpoints produce identical output to those on shared endpoints?
- If any divergence: investigate cause (timing, model version mismatch, prompt difference, hardware difference)
- Document convergence rate and any issues

**2.8.4 — Edge case testing** (1-2 days)
- Test: sidecar starts after round announcement (late joiner)
- Test: sidecar loses connection during round
- Test: sidecar wallet runs out of funds
- Test: one sidecar deliberately submits wrong scores (should diverge in convergence check)
- Test: commit deadline passes with only 2/4 commits (round should still work)

**Deliverables:**
- All 4 devnet validators running sidecars
- Multiple successful commit-reveal rounds
- Convergence analysis results
- Edge case test results

---

### Milestone 2.9: Testnet Rollout

**Duration:** ~5-7 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestone 2.8

**Goal:** Roll out Phase 2 to testnet validators.

**Steps:**

**2.9.1 — Foundation validator sidecars** (1-2 days)
- Install sidecars on the 5 foundation testnet validators first
- Run 1-2 scoring rounds with only foundation validators participating
- Verify convergence among foundation validators

**2.9.2 — Community announcement** (1 day)
- Post the prepared announcement on Discord and Telegram
- Share documentation link and ChatGPT agent link
- Offer support for setup questions
- No hard deadline — validators can join at their own pace

**2.9.3 — Monitor community participation** (ongoing, ~3-5 days)
- Track: how many validators install sidecars
- Track: commit/reveal participation rates per round
- Respond to support requests
- Iterate on documentation based on feedback

**2.9.4 — Stabilization** (1-2 days)
- Run multiple rounds with growing participation
- Monitor convergence rates as more validators join
- Document any systematic issues

**Deliverables:**
- Phase 2 live on testnet
- Foundation + community validators participating
- Convergence monitoring dashboard populated
- Documentation updated based on feedback

---

### Phase 2 Decision Gate

**Criteria for proceeding to Phase 3A:**

| Criterion | Required | Status |
|---|---|---|
| Phase 2 running on testnet for 4+ weeks | Yes | |
| At least 10 validators participating in commit-reveal | Yes | |
| Convergence rate > 90% consistently | Yes | |
| Divergence causes identified and documented | Yes | |
| Output convergence confirmed | Yes | |
| `featureDynamicUNL` amendment defined in postfiatd | Yes | |

**Additional criteria for Phase 3 Research (proof-of-logits):**

| Criterion | Required | Status |
|---|---|---|
| Logit-level determinism tested empirically (same GPU type) | Yes | |
| Phase 2 convergence rates indicate logit proofs are worthwhile | Decision point | |

---

## Phase 3A: Content Authority Transfer

**Duration:** ~2-3 weeks | **Difficulty:** ★★★★☆ Hard

**Goal:** Transfer UNL content authority from the foundation to converged validator results. The foundation still publishes the VL but the content comes from what validators agree on. If convergence drops, the system falls back to foundation-only scoring.

```
         M 3.4                  M 3.5 (parallel)
         Authority              Identity
         Transfer               Portal
         ~5-7 days              ~7-10 days
              │                      │
              ▼                      │
         M 3.6                      │
         System Test   ◄────────────┘
         ~5-7 days
```

## Phase 3 Research: Proof of Logits (Conditional)

**Status:** Research milestone — proceed only if Phase 2 convergence rates justify the investment. If Phase 2 achieves >99% output convergence reliably, logit proofs are less critical. If not pursued, the system operates at Phase 2 + 3A level with output-level convergence.

```
         M 3.1                  M 3.2
         Logit Commitment       Spot-Check
         Generation             Tooling
         ~7-10 days             ~7-10 days
              │                      │
              └──────────┬───────────┘
                         ▼
                    M 3.3
                    Verif.
                    Publish
                    ~5-7 days
```

---

### Milestone 3.1: Logit Commitment Generation (Research)

**Duration:** ~7-10 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Phase 2 complete, decision to proceed with logit proofs

**Goal:** Modify the sidecar's inference engine to capture SHA-256 hashes of logit vectors at every token position during generation.

**Steps:**

**3.1.1 — Inference engine modification** (3-5 days)
- Hook into the inference engine (SGLang) to intercept logit vectors at each decoding step
- At each token position `i`:
  1. Get the raw logit vector (float array over vocabulary, typically 32K-128K entries)
  2. Serialize the logit vector to bytes (consistent byte ordering — little-endian float32)
  3. Compute `SHA-256(serialized_logits)`
  4. Store the hash alongside the generated token
- The result is an ordered list of hashes — the **logit commitment**:
  ```json
  {
    "logit_commitment": [
      {"position": 0, "token_id": 1234, "logit_hash": "a1b2c3..."},
      {"position": 1, "token_id": 5678, "logit_hash": "d4e5f6..."},
      ...
    ],
    "total_positions": 1500,
    "commitment_hash": "<sha256 of all logit hashes concatenated>"
  }
  ```

**3.1.2 — Deterministic inference validation** (2-3 days)
- Run the same prompt through the inference engine multiple times on the same GPU
- Verify: are logit hashes identical across runs? (they must be for this to work)
- If not: investigate inference engine settings, quantization, CUDA determinism flags
- Test across multiple instances of the same GPU type (e.g., two A40s on Modal)
- Document results and any required settings

**3.1.3 — Integration with commit-reveal** (2 days)
- Update the sidecar's commit-reveal flow:
  - Commit hash now includes: `sha256(scores_json + logit_commitment_hash + salt + round_number)`
  - Reveal payload now includes: logit commitment (published to IPFS alongside scores)
- Update memo formats:
  ```json
  {
    "type": "pf_scoring_reveal_v2",
    "round_number": 42,
    "validator_public_key": "nHUDXa2b...",
    "scores_ipfs_cid": "Qm...",
    "logit_commitment_ipfs_cid": "Qm...",
    "salt": "...",
    "scores_hash": "...",
    "logit_commitment_hash": "..."
  }
  ```

**Deliverables:**
- Inference engine with logit hash capture at every token position
- Deterministic inference validated on mandatory GPU type
- Updated commit-reveal protocol with logit commitments
- Test results documenting cross-instance logit hash consistency

---

### Milestone 3.2: Cross-Validator Spot-Check Tooling (Research)

**Duration:** ~7-10 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Milestone 3.1

**Goal:** Build tooling that allows any validator (or external party) to spot-check any other validator's logit commitments.

**Steps:**

**3.2.1 — Spot-check engine** (3-5 days)
- Implement `SpotChecker` class:
  1. Input: target validator's logit commitment + published scores + round snapshot
  2. Derive challenge positions from a **future validated ledger hash** — use the hash of a ledger that closes after the reveal window ends. This makes positions unpredictable at commit time, preventing validators from precomputing logits at only the challenged positions.
  3. Pick N positions from the derived seed (configurable, default 5-10)
  4. For each position `K`:
     - Load the same model (verified by weight hash)
     - Feed the same input (snapshot + prompt, verified from IPFS)
     - Run forward pass up to position `K`
     - Compute `SHA-256(logits_at_position_K)`
     - Compare with the target validator's published hash at position `K`
  4. Report results: pass/fail per position, overall verdict

**3.2.2 — Spot-check scheduling** (2-3 days)
- After each round's reveal window:
  - The foundation's scoring service performs minimum 3 spot-checks per validator
  - Each validator's sidecar can optionally spot-check other validators
  - External parties can spot-check at any time using the published data
- Spot-check results are collected and included in the convergence report

**3.2.3 — Verification CLI tool** (2 days)
- Standalone CLI tool (included in the sidecar repo) for manual spot-checking:
  ```bash
  python -m sidecar.verify \
    --round 42 \
    --validator nHUDXa2b... \
    --positions 5 \
    --model-path /path/to/model \
    --ipfs-gateway https://ipfs-testnet.postfiat.org
  ```
- Downloads all necessary data (snapshot, scores, logit commitment) from IPFS
- Runs spot-checks and prints results
- Can be used by anyone with GPU access

**Deliverables:**
- `SpotChecker` implementation
- Automated spot-checking in foundation scoring service
- Standalone verification CLI tool
- Documentation for external verifiers

---

### Milestone 3.3: Verification Result Publication (Research)

**Duration:** ~5-7 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 3.2

**Goal:** Publish verification results and update the convergence report format.

**Steps:**

**3.3.1 — Extended convergence report** (2-3 days)
- Update convergence report to include Layer 2 verification:
  ```json
  {
    "round_number": 42,
    "layer_1": {
      "convergence_rate": 0.96,
      "output_hash_matches": 26,
      "total_reveals": 27
    },
    "layer_2": {
      "spot_checks_performed": 135,
      "spot_checks_passed": 132,
      "spot_checks_failed": 3,
      "validators_verified": 27,
      "validators_failed": 1,
      "failure_details": [
        {
          "validator": "nHxyz...",
          "position": 342,
          "expected_hash": "abc...",
          "actual_hash": "def...",
          "verdict": "logit_mismatch"
        }
      ]
    }
  }
  ```

**3.3.2 — Mismatch handling** (2-3 days)
- Validators that fail spot-checks:
  - Excluded from that round's convergence calculation
  - Logged in the convergence report with evidence
  - No slashing — exclusion is the penalty
  - Repeated failures across rounds flagged for investigation
- Update the `pf_scoring_convergence_v1` memo to include Layer 2 summary

**3.3.3 — Monitoring dashboard update** (1 day)
- Update the scoring service API to expose Layer 2 data
- Per-validator: spot-check history, pass/fail rate across rounds

**Deliverables:**
- Extended convergence report with Layer 2 data
- Mismatch handling logic
- Updated monitoring endpoints

---

### Milestone 3.4: Authority Transition

**Duration:** ~5-7 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Phase 2 convergence proven

**Goal:** Transition from "foundation UNL is authoritative" to "converged validator UNL is authoritative." This is a Phase 3A milestone — it does not require proof-of-logits, only proven Phase 2 output convergence.

**Steps:**

**3.4.1 — Define transition criteria** (1 day)
- The converged validator UNL becomes authoritative when:
  - At least 10 validators consistently participate (4+ consecutive rounds)
  - Output convergence rate > 95% for 4+ consecutive rounds
  - The `featureDynamicUNL` amendment is voted and enabled
- If convergence drops below threshold for N consecutive rounds, automatically revert to foundation-only UNL

**3.4.2 — Implement UNL source selection in scoring service** (2-3 days)
- Update the scoring orchestrator:
  - If convergence criteria met: use the converged validator UNL (median of validator outputs)
  - If not met: fall back to foundation's UNL
  - The switch is automatic based on convergence data
- The foundation still publishes the VL — but the VL content now comes from the converged result, not the foundation's own scoring

**3.4.3 — postfiatd amendment activation** (2-3 days)
- When ready: activate `featureDynamicUNL` amendment via validator voting
- This is a protocol-level change that signals validators support the Dynamic UNL system
- The amendment itself may not gate code changes in Phase 3 (the VL format doesn't change), but it serves as a coordination mechanism

**Deliverables:**
- Transition criteria defined and implemented
- Automatic UNL source selection based on convergence
- Amendment activation plan

---

### Milestone 3.5: Validator Identity Verification & Scoring Integration

**Duration:** ~9-13 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** None (parallel work — can be built anytime during Phase 1-3, does not gate any other milestone)

**Goal:** Define the identity memo schema, provide a web interface where validators can complete identity verification (KYC/KYB via SumSub), and integrate identity data into the scoring pipeline.

**Note:** The identity verification approach and memo schema have not been finalized yet. The scoring-onboarding repository serves as a reference for the memo publishing pattern (hex encoding, transaction structure) but identity verification will not live in that repo. The exact implementation approach should be determined when this milestone is reached. Below is an approximate scope.

**Important distinction:** Validators need on-chain identity data for meaningful scoring (the LLM needs to know who it's scoring). The scoring pipeline in Phase 1 launches without identity data — all validators get `identity: null` and the LLM scores them with lower identity/reputation scores accordingly. This milestone adds identity data when the verification design is ready.

**Steps:**

**3.5.1 — Evaluate extension options** (1 day)
- Option A: Extend the existing scoring-onboarding web UI and API
- Option B: Build a standalone portal that integrates with the existing SumSub setup
- Recommend Option A if the existing codebase is maintainable

**3.5.2 — Validator identity flow** (3-5 days)
- Validator visits the portal and connects their validator public key
- Portal guides them through:
  1. Wallet authorization (sign a message with their validator key)
  2. KYC verification (redirect to SumSub, complete verification)
  3. Optional: domain verification (prove they control a domain)
  4. Optional: institutional verification (KYB)
- On completion: identity proofs published on-chain (existing memo pattern)

**3.5.3 — Define identity memo schema** (1 day)
- Define the on-chain memo format for identity attestations (`pf_identity_v1`, `pf_wallet_auth_v1`)
- Specify: memo type strings, hex-encoded JSON payload structure, required vs optional fields
- Fields: `verified` (bool), `entity_type` (institutional/individual/unknown), `domain_attested` (bool)
- Use scoring-onboarding as reference for the memo publishing pattern (hex encoding, transaction structure)
- Document the schema so both the publisher (portal) and reader (scoring service) agree on the format

**3.5.4 — Identity client for scoring pipeline** (1-2 days)
- Implement `IdentityClient` class in `scoring_service/clients/identity.py`
- Read identity verification memo transactions from the PFTL chain:
  - Use the PFTL RPC `account_tx` method to fetch transactions from the identity publisher address
  - Parse memo data (hex → JSON) using the schema defined in 3.5.3
  - Extract attestation status only — no PII
- Populate `IdentityAttestation` on each `ValidatorProfile`
- Validators without identity data get `identity: null` — the LLM penalizes under identity/reputation
- Index results into local PostgreSQL for fast lookup in future rounds

**3.5.5 — Documentation** (1 day)
- Guide for validators on how to complete identity verification
- Add to the ChatGPT agent's knowledge base

**Deliverables:**
- Validator identity verification portal
- Identity memo schema definition
- `IdentityClient` integrated into the scoring pipeline
- On-chain identity publication
- Documentation

---

### Milestone 3.6: Full System Test

**Duration:** ~5-7 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestones 3.4, 3.5

**Goal:** End-to-end test of the Phase 3A system on testnet — converged validator UNL as the authoritative source.

**Steps:**

**3.6.1 — Full round execution** (2-3 days)
- Run multiple scoring rounds with:
  - Foundation scoring (Phase 1 pipeline)
  - Validator verification with commit-reveal (Phase 2)
  - Convergence check (output hash comparison)
  - Authority transition active (converged UNL published as authoritative)
- Verify all data is published to IPFS and on-chain

**3.6.2 — Authority transition test** (1-2 days)
- Verify the transition: converged validator UNL becomes the published VL
- Verify all testnet validators accept the converged UNL
- Monitor consensus stability during and after transition
- Test fallback: if convergence drops, does the system revert to foundation UNL?
- Test participation fallback: what happens if fewer than the minimum validators participate?

**3.6.3 — Adversarial testing** (1-2 days)
- Test: one validator deliberately runs a different model → should diverge in convergence check
- Test: one validator copies another's output hash without running the model → caught by commit-reveal timing (must commit before seeing others)
- Test: foundation goes offline → validators still converge among themselves (future resilience)

**3.6.4 — Operational failure drills** (1-2 days)
- Test: foundation doesn't announce a round → no round occurs, previous UNL stays active
- Test: IPFS gateway goes down → validators fetch from HTTPS fallback or alternative gateway
- Test: one-third of validators fail to reveal → round still completes with reduced participation, convergence rate reflects the dropoff
- Test: VL expires before the next round publishes a new one → what happens to consensus? (validators should continue with last known VL)
- Test: model upgrade half-applied (some validators on old version, some on new) → convergence check should detect the split via environment diff
- Test: signing service unavailable → offline signing tool can publish an emergency VL

**Deliverables:**
- Complete system test results
- Authority transition verified with fallback behavior confirmed
- Adversarial test results
- Operational failure drill results
- System declared production-ready for testnet

---

## Summary: Time and Difficulty by Phase

| Phase | Duration | Difficulty | Key Deliverables |
|---|---|---|---|
| **Phase 0** | ~1 week | ★★★☆☆ | **Complete.** Model selected, Modal deployed, 100% determinism confirmed |
| **Phase 1** | ~4-6 weeks | ★★★★☆ | Foundation scoring live on testnet, VL auto-generated |
| **Phase 2** | ~6-8 weeks | ★★★★★ | Validator GPU sidecars, commit-reveal, convergence monitoring |
| **Phase 3A** | ~2-3 weeks | ★★★★☆ | Authority transition, identity verification & scoring integration, system test |
| **Phase 3 Research** | ~5-7 weeks | ★★★★★ | Proof-of-logits (conditional — only if Phase 2 convergence justifies) |
| **Total (through 3A)** | **~14-19 weeks** | | **Converged validator UNL as authoritative source** |

## Summary: Time and Difficulty by Milestone

| Milestone | Duration | Difficulty | Dependencies |
|---|---|---|---|
| **0.1** Model Selection | 2-3 days | ★★★☆☆ | Done |
| **0.2** Modal Setup | 1-2 days | ★★☆☆☆ | Done |
| **0.3** Determinism Research | 2 days | ★★★★☆ | Done — 100% confirmed |
| **0.4** Geolocation Setup & Legal | 1 day | ★☆☆☆☆ | Not yet addressed |
| **1.1** Scoring Service Repo Setup | 1-2 days | ★★☆☆☆ | Phase 0 — Done |
| **1.2** Infrastructure Provisioning | 1 day | ★★☆☆☆ | 1.1 — Done |
| **1.3** postfiatd Version Update | 3-4 days | ★★★☆☆ | 1.2 — Done |
| **1.4** Data Collection Pipeline | 3-4 days | ★★★☆☆ | 1.1, 1.3 — Done |
| **1.5** LLM Scoring Integration | 4-5 days | ★★★☆☆ | 1.1, 1.4 — Done |
| **1.6** VL Generation | 3-4 days | ★★★☆☆ | 1.5 — Done |
| **1.7** IPFS Audit Trail | 2-3 days | ★★☆☆☆ | 1.4, 1.5 — Done |
| **1.8** On-Chain Memo | 1-2 days | ★★☆☆☆ | 1.6, 1.7 — Done |
| **1.9** Orchestrator & Scheduler | 3-4 days | ★★★☆☆ | 1.4-1.8 — Done |
| **1.10** Devnet Testing & Validation | 13-19 days | ★★★☆☆ | 1.2, 1.9 — In progress (1.10.1-1.10.5 done) |
| **1.11** Admin Override Endpoints | 3-5 days | ★★★☆☆ | 1.10.6, 1.10.7 |
| **1.12** Explorer Scoring Pages | 9-14 days | ★★★☆☆ | 1.10.5 |
| **1.13** Testnet Deployment | 3-5 weeks elapsed (~4-6 days active) | ★★★☆☆ | 1.10, 1.11 |
| **2.1** Commit-Reveal Design | 2-3 days | ★★★★☆ | Phase 1 |
| **2.2** Sidecar Repo | 1-2 days | ★★☆☆☆ | 2.1 |
| **2.3** Sidecar Inference | 7-10 days | ★★★★☆ | 2.2 |
| **2.4** Sidecar Chain | 5-7 days | ★★★★☆ | 2.1, 2.3 |
| **2.5** Convergence Monitor | 5-7 days | ★★★☆☆ | 2.4 |
| **2.6** Validator Onboarding | 1-2 days | ★★☆☆☆ | 2.3, 2.4 |
| **2.7** postfiatd Changes | 5-7 days | ★★★★☆ | Phase 1, 2.1 |
| **2.8** Devnet Testing | 5-7 days | ★★★☆☆ | 2.4, 2.5, 2.7 |
| **2.9** Testnet Rollout | 5-7 days | ★★★★☆ | 2.8 |
| **3.4** Authority Transfer | 5-7 days | ★★★★★ | Phase 2 convergence proven |
| **3.5** Identity Verification & Scoring Integration | 9-13 days | ★★★☆☆ | None (parallel) |
| **3.6** Full System Test | 5-7 days | ★★★★☆ | 3.4, 3.5 |
| **3.1** Logit Commitments | 7-10 days | ★★★★★ | Phase 2 (research, conditional) |
| **3.2** Spot-Check Tooling | 7-10 days | ★★★★★ | 3.1 (research, conditional) |
| **3.3** Verification Publish | 5-7 days | ★★★☆☆ | 3.2 (research, conditional) |
