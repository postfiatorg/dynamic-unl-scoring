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
| **Phase 1** | Foundation Scoring Pipeline | 11 | 4 | `████████░░░░░░░░░░░░` 36% |
| **Phase 2** | Validator Verification (GPU Sidecars) | 9 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Phase 3** | Authority Transfer & Proof-of-Logits | 6 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Total** | | **30** | **8** | `█████░░░░░░░░░░░░░░░` **27%** |

---

## Changes from Original Plan

Phase 0 revealed several constraints not anticipated in the original plan. The core design is unchanged — only the model and infrastructure differ.

| Area | Original Plan | Actual Outcome | Why |
|---|---|---|---|
| **Model** | 7B-32B (e.g. Qwen 2.5-32B) | Qwen3-Next-80B-A3B-Instruct-FP8 (80B MoE, 3B active) | Two benchmark rounds tested 7 models. Smaller models lacked scoring quality. 80B MoE fits on single H200 at ~75 GB with FP8. |
| **GPU platform** | RunPod serverless | Modal serverless | RunPod's SGLang is broken (9 attempts, community confirmed). RunPod also doesn't recognize the Qwen3-Next architecture. |
| **GPU type** | A40/L4/A100 (consumer-accessible) | H200 (141 GB) | Model requires ~75 GB VRAM + 36 GB Mamba cache. Only H200+ has enough headroom for single-GPU deterministic inference. |
| **Quantization** | GPTQ-Int4 or AWQ | FP8 (native) | GPTQ/AWQ trigger Marlin repacking OOM on large MoE models. FP8 avoids repacking entirely. |
| **Determinism** | Research + harness design only | 100% confirmed empirically | 5 full scoring runs produced bit-identical output. Exceeds the >99% target for Phase 2 entry. |
| **Milestone 0.4 (Geolocation)** | MaxMind + ASN setup | Complete — pyasn for ASN, DB-IP Lite for country-level geolocation | ASN data is public/publishable (IPFS). Geolocation uses DB-IP Lite (CC BY 4.0, freely publishable). MaxMind dropped from the scoring pipeline — its EULA prohibits republishing derived data, which conflicts with IPFS audit trail publication and Phase 2 reproducibility (validators would each need a MaxMind license). |

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

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.1, 1.3 | **Status:** ✅ Complete

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

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.5

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

**1.6.3 — VL serving and devnet config update** 🔄 (0.5-1 day)
- Serve the VL from the scoring service at `GET /vl.json` (reads latest VL from PostgreSQL)
- Each environment has its own scoring service instance, so the domain differentiates:
  - Devnet: `https://scoring-devnet.postfiat.org/vl.json`
  - Testnet: `https://scoring-testnet.postfiat.org/vl.json`
- **Devnet config change (prerequisite for testing):** Devnet currently uses a static `[validators]` block in `validators-devnet.txt`. Update it to use `[validator_list_sites]` + `[validator_list_keys]` pointing to the scoring service URL and the devnet publisher master key. This requires a postfiatd release and rolling restart of the 4 devnet validators.
- **Devnet publisher key generation:** Generate a new publisher key pair for devnet using `validator-keys create_keys` + `validator-keys create_token` (existing C++ tool in the postfiatd build). The token goes into the `DEVNET_VL_PUBLISHER_TOKEN` GitHub secret; the master public key goes into `validators-devnet.txt`.

**1.6.4 — Validation** (0.5 day)
- Verify generated VL can be decoded by `generate_vl.py --decode`
- Verify a postfiatd node accepts the generated VL (test on devnet)

**Deliverables:**
- `VLGeneratorService` that produces a signed VL JSON from a ranked validator list
- Sequence number tracking in PostgreSQL
- VL serving endpoint (`GET /vl.json`)
- Devnet validator configs updated to fetch VL from scoring service
- Verification that postfiatd accepts the generated VL

**Security note:** The publisher signing key is the most sensitive secret in this system. It must be stored securely (environment variable, never in code or logs). If this key is compromised, an attacker could publish a malicious UNL. Required mitigations for Phase 1:
- Separate keys for devnet and testnet (never share signing keys across environments)
- Publisher key is fully configurable via `VL_PUBLISHER_TOKEN` env var — key rotation is an env var change + node config update + rolling restart
- Access logging for every signing operation (log round number, timestamp, VL hash — never log the key itself)
- Manual offline emergency signing tool: a standalone CLI script that can sign and publish a VL without the scoring service running (for use if the service is compromised or unavailable)
- For mainnet (future): upgrade to HSM or Vault transit for key storage

**Testnet transition plan (executed during M1.11):**
- Testnet nodes currently fetch VL from `https://postfiat.org/testnet_vl.json` with publisher key `ED3F1E...`
- Transition sequence:
  1. Ship a postfiatd release that updates `validators-testnet.txt` with the new URL (`scoring-testnet.postfiat.org/vl.json`) and new testnet publisher key
  2. The scoring service serves the VL at the new endpoint (can initially serve a static VL matching the current validator set while verifying correctness)
  3. Wait until most community validators have upgraded — non-upgraded nodes continue fetching the old VL from the old URL, which stays valid until its expiration date
  4. Once validator adoption is confirmed, enable dynamic scoring for testnet
- No proxy needed, no flag day — old and new coexist during the transition window

---

### Milestone 1.7: IPFS Audit Trail Publication

**Duration:** ~2-3 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestones 1.4, 1.5

**Goal:** Publish the full scoring audit trail to IPFS after each round.

**Steps:**

**1.7.1 — IPFS client** (1-2 days)
- Implement `IPFSClient` class that pins content to the self-hosted IPFS node:
  ```
  POST https://ipfs-testnet.postfiat.org/api/v0/add
  Authorization: Basic <base64(admin:password)>
  Content-Type: multipart/form-data
  ```
- Support pinning JSON files and directory structures
- Return the CID (Content Identifier) for each pinned item
- Handle: upload failures, retries, timeout

**1.7.2 — Audit trail assembly and publication** (1-2 days)
- After each scoring round, publish to IPFS:
  ```
  round_<N>/
  ├── snapshot.json           # Normalized validator data snapshot (scorer input)
  ├── raw/                    # Raw API responses (verifiable audit trail)
  │   ├── vhs_validators.json # Raw VHS response, timestamped
  │   ├── vhs_topology.json   # Raw VHS topology response
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
- Pin to a secondary service (Pinata or web3.storage) for redundancy — if the foundation's IPFS node goes down, the data is still accessible
- Serve audit trail artifacts over plain HTTPS as a fallback (e.g., `https://scoring-testnet.postfiat.org/rounds/<N>/`)
- Store CID in PostgreSQL linked to the round
- Note: validators can fetch by CID through any IPFS gateway, not just the foundation's

**Deliverables:**
- `IPFSPublisherService` that pins the audit trail and returns a CID
- Secondary pin to a redundant service
- HTTPS fallback serving of audit trail artifacts
- Audit trail directory structure defined and implemented

---

### Milestone 1.8: On-Chain Memo Publication

**Duration:** ~2-3 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestones 1.6, 1.7

**Goal:** Publish the UNL hash and IPFS CID on-chain as a memo transaction, following the pattern from scoring-onboarding.

**Steps:**

**1.8.1 — Memo format definition** (0.5 day)
- Define the memo format for UNL publication:
  ```json
  {
    "type": "pf_dynamic_unl_v1",
    "round_number": 1,
    "unl_hash": "<sha512Half of VL JSON blob, hex>",
    "ipfs_cid": "Qm...<root CID of audit trail>",
    "vl_sequence": 42,
    "model_version": "Qwen2.5-32B-Instruct",
    "model_weight_hash": "sha256:abc123...",
    "prompt_version": "v1.0.0",
    "validator_count": 30,
    "published_at": "2026-03-15T00:00:00Z"
  }
  ```
- Memo type: `pf_dynamic_unl` (hex-encoded)

**1.8.2 — Transaction submission** (1-2 days)
- Reuse the scoring-onboarding `PFTLClient` pattern:
  - Build Payment transaction (1 drop) with memo
  - Hex-encode memo data and memo type
  - Autofill, sign, submit via `xrpl-py`
- The destination address: a designated memo receiver (same pattern as scoring-onboarding, or self-send)
- Log transaction hash in PostgreSQL
- Handle: submission failures, retries (same scheduler pattern as scoring-onboarding)

**1.8.3 — Retry mechanism** (0.5-1 day)
- If transaction submission fails: mark as pending, retry via scheduler
- Admin endpoint for manual retry: `POST /admin/retry-publish`

**Deliverables:**
- `OnChainPublisherService` that submits UNL publication memo transactions
- Retry mechanism for failed submissions
- Transaction logging in PostgreSQL

---

### Milestone 1.9: Scoring Orchestrator & Scheduler

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.4-1.8

**Goal:** Wire all services together into a state machine orchestrator with idempotent steps, scheduled and on-demand execution, and replay/rebuild capabilities.

**Steps:**

**1.9.1 — State machine orchestrator** (2-3 days)
- Implement `ScoringOrchestrator` as an explicit state machine with these states:
  ```
  COLLECTING → NORMALIZED → SCORED → SELECTED → VL_SIGNED →
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
  - `replay_round(round_id)` — re-run a completed round from its saved snapshot (useful for debugging)
  - `rebuild_from_raw(round_id)` — re-normalize from raw evidence and re-score (verifies the full chain)

**1.9.2 — Scheduler** (0.5-1 day)
- Use a `scoring_schedule` table in Postgres with advisory locks for singleton orchestration (no APScheduler in-process)
  - Default cadence: every 168 hours (weekly), configurable via `SCORING_CADENCE_HOURS`
  - Advisory lock ensures only one round runs at a time, even with multiple service instances
  - A background task checks the schedule table and triggers rounds when due

**1.9.3 — Manual trigger** (0.5 day)
- API endpoint: `POST /api/scoring/trigger` — triggers an immediate scoring round
- `POST /api/scoring/trigger?dry_run=true` — dry run mode
- `POST /api/scoring/replay/<round_id>` — replay a previous round
- Requires admin authentication (API key or basic auth)
- Returns the round ID for tracking
- CLI script `scripts/trigger_round.py` that calls this endpoint

**1.9.4 — Status API** (0.5 day)
- `GET /api/scoring/rounds` — list recent rounds with status and current state
- `GET /api/scoring/rounds/<id>` — detailed round info (all hashes, CIDs, timestamps, state transition log)
- `GET /api/scoring/current-unl` — current active UNL (latest successful round)

**Deliverables:**
- `ScoringOrchestrator` as a state machine with idempotent steps
- dry_run, replay_round, rebuild_from_raw capabilities
- Postgres-based scheduling with advisory locks
- Manual trigger + status API endpoints
- Round tracking with state transition audit log

---

### Milestone 1.10: Devnet Testing & Validation

**Duration:** ~5-7 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.2, 1.9

**Goal:** Run the full scoring pipeline on devnet, verify end-to-end correctness, iterate on prompt quality.

**Steps:**

**1.10.1 — First deployment to devnet** (1-2 hours)
- Create `devnet` branch from main, push to trigger deploy workflow
- Verify automated deployment succeeds: image built, pushed to Docker Hub, deployed to Vultr
- Verify health endpoint: `curl https://scoring-devnet.postfiat.org/health`
- Verify API docs: `https://scoring-devnet.postfiat.org/docs` (FastAPI auto-docs)

**1.10.2 — First scoring round** (1 day)
- Trigger a manual scoring round on devnet
- Verify each step:
  - Data collected from VHS (check snapshot.json)
  - LLM called successfully (check scores.json — are scores reasonable?)
  - VL generated and signed (decode with `generate_vl.py --decode`)
  - Audit trail pinned to IPFS (fetch via gateway, verify content)
  - Memo transaction submitted on-chain (check via RPC)
  - VL served at configured URL

**1.10.3 — Node verification** (1-2 days)
- Point one devnet validator to the new VL URL (update `[validator_list_sites]` in config)
- Restart the validator
- Verify: validator fetches the new VL, applies it, consensus continues normally
- Check logs for any VL verification errors
- Once confirmed: update all 4 devnet validators

**1.10.4 — Prompt iteration** (2-3 days)
- Review LLM scoring output quality:
  - Are scores differentiated? (not all 85-90)
  - Does reasoning reference actual validator metrics?
  - Does geographic diversity factor in? Are the specified diversity dimensions (country, ASN, cloud provider, datacenter, operator) reflected in the scoring?
  - Are KYC-verified validators scored appropriately?
- Iterate on the prompt based on output quality
- Run 3-5 scoring rounds, compare results
- Finalize prompt version

**1.10.5 — Scoring stability testing** (1-2 days)
- Replay the same snapshot multiple times (5-10 runs) — scores should be consistent across runs
- One-candidate-added / one-candidate-removed test — existing validator scores should not shift significantly when an unrelated validator is added or removed from the snapshot
- Measure natural score variance across rounds to determine the minimum score gap config value for churn control (Milestone 1.5.4)
- Validate that the churn control mechanism behaves as expected: borderline validators should not oscillate between rounds

**1.10.6 — Edge case testing** (1-2 days)
- Test: what happens when VHS is down? (data collection should fail gracefully, round marked failed)
- Test: what happens when Modal cold-starts? (should wait and retry)
- Test: what happens when IPFS is unreachable? (should retry)
- Test: what happens when PFTL node is down? (memo submission should retry)
- Test: what happens with 0 validators? (should produce empty UNL, not crash)
- Test: scheduler runs correctly at configured interval

**Deliverables:**
- Multiple successful scoring rounds on devnet
- All 4 devnet validators running with dynamic VL
- Finalized scoring prompt
- Edge case test results documented

---

### Milestone 1.11: Testnet Deployment

**Duration:** ~3-4 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.10

**Goal:** Deploy the scoring pipeline to testnet and transition ~30 validators to the dynamically generated VL.

**Steps:**

**1.11.1 — Testnet scoring round** (1 day)
- Trigger a manual scoring round on testnet
- Verify all steps work with real testnet data (~30 validators)
- Review scores: do they make sense for the actual testnet validator set?
- Check: does the prompt handle 30 validators within context window?

**1.11.2 — VL transition strategy** (0.5 day)
- Since testnet validators already fetch from `https://postfiat.org/testnet_vl.json`:
  - Option A: Have the scoring service upload to this same URL (requires access to the web server)
  - Option B: Update the URL to `https://scoring-testnet.postfiat.org/vl.json` (requires all validators to update config)
- Choose option and prepare

**1.11.3 — Transition execution** (1-2 days)
- If Option A: configure scoring service to upload VL to the existing URL after each round
- If Option B: announce on Discord/Telegram that validators must update their config, provide exact instructions, give a transition window (e.g., 1 week), then switch
- Monitor: are all validators picking up the new VL? Check VHS for agreement scores.

**1.11.4 — Monitoring and stabilization** (1-2 days)
- Run 2-3 weekly scoring rounds
- Monitor: consensus stability, VL acceptance rate, any validator complaints
- Address any issues that arise

**Deliverables:**
- Scoring pipeline running on testnet
- All testnet validators consuming the dynamically generated VL
- At least 2 successful weekly scoring rounds completed
- No consensus disruptions

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
| Determinism research complete (Milestone 0.3) | Yes | |
| Reproducibility harness built and run — >99% output equality on mandatory GPU type | Yes | |
| Mandatory GPU type selected for Phase 2 | Yes | |

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
| **1.1** Repo Setup | 1-2 days | ★★☆☆☆ | Phase 0 |
| **1.2** Data Collection | 3-4 days | ★★★☆☆ | 1.1 |
| **1.3** LLM Scoring | 4-5 days | ★★★☆☆ | 1.1, Phase 0 |
| **1.4** VL Generation | 3-4 days | ★★★☆☆ | 1.3 |
| **1.5** IPFS Publication | 2-3 days | ★★☆☆☆ | 1.2, 1.3 |
| **1.6** On-Chain Memo | 2-3 days | ★★☆☆☆ | 1.4, 1.5 |
| **1.7** Orchestrator | 3-4 days | ★★★☆☆ | 1.2-1.6 |
| **1.8** Infra Deploy | 2-3 days | ★★☆☆☆ | 1.7 |
| **1.9** Devnet Testing | 5-7 days | ★★★☆☆ | 1.8 |
| **1.10** Testnet Deploy | 3-4 days | ★★★☆☆ | 1.9 |
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
