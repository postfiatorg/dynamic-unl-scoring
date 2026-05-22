# Dynamic UNL: Implementation Milestones

Updated after M2.0 completion (2026-05-20). Original plan lives in `postfiatd/docs/dynamic-unl/ImplementationPlan.md`. This version reflects what actually happened and adjusts the remaining phases accordingly.

**Difficulty scale:** ★☆☆☆☆ Trivial | ★★☆☆☆ Easy | ★★★☆☆ Medium | ★★★★☆ Hard | ★★★★★ Very Hard

**Time estimates** assume a solo developer with heavy LLM-assisted development (Claude Code, Codex).

**Reference design:** All architectural decisions, trust models, and protocol details are defined in [Design.md](Design.md). This document covers *how* and *when* to build it, not *what* to build.

---

## Overview

| Phase | Description | Milestones | Complete | Progress |
|-------|-------------|-----------|----------|----------|
| **Phase 0** | Research & Validation | 4 | 4 | `████████████████████` 100% |
| **Phase 1** | Foundation Scoring Pipeline | 13 | 13 | `████████████████████` 100% |
| **Phase 2** | Validator Shadow Verification | 10 | 1 | `██░░░░░░░░░░░░░░░░░░` 10% |
| **Model Governance** | Model and Judge Governance | 6 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Phase 3A** | Authority Transfer | 3 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Phase 3 Research** | Proof-of-Logits (Conditional) | 3 | 0 | `░░░░░░░░░░░░░░░░░░░░` 0% |
| **Total** | | **39** | **18** | `█████████░░░░░░░░░░░` **46%** |

M2.0 is counted as the first completed Phase 2 milestone because the staged final audit bundle and execution manifest work is complete on `main`. M2.0 does not create the separate pre-scoring input package. M2.1, Frozen Input Package Lifecycle, adds that input-only package and the `INPUT_FROZEN` boundary.

---

## Changes from Original Plan

Phase 0 and the first devnet scoring round revealed several constraints not anticipated in the original plan. The core design is unchanged — only the model, infrastructure, and a handful of VL publication details differ.

| Area | Original Plan | Actual Outcome | Why |
|---|---|---|---|
| **Model** | 7B-32B (e.g. Qwen 2.5-32B) | Active: Qwen/Qwen3.6-27B-FP8 (`qwen36-27b-fp8`); historical Phase 0 baseline: Qwen3-Next-80B-A3B-Instruct-FP8 | Phase 0 selected Qwen3-Next after two benchmark rounds. The later Qwen3.6 re-evaluation selected Qwen3.6 as the active scorer because it better matches the current scoring rubric and deploys cleanly on the pinned Modal/SGLang profile. |
| **GPU platform** | RunPod serverless | Modal serverless | RunPod's SGLang path was dropped during Phase 0. Modal remains the shared endpoint platform for the active Qwen3.6 scorer and the historical Qwen3-Next baseline. |
| **GPU type** | A40/L4/A100 (consumer-accessible) | Active: H100 for Qwen3.6; historical baseline: H200 for Qwen3-Next | Qwen3.6 uses an FP8 checkpoint with native H100 FP8 support. Qwen3-Next required H200 headroom for its larger FP8 weights and Mamba state cache. |
| **Quantization** | GPTQ-Int4 or AWQ | FP8 checkpoint | GPTQ/AWQ triggered Marlin repacking OOM on the large Phase 0 MoE baseline. The active Qwen3.6 profile serves the FP8 checkpoint directly and lets SGLang auto-detect the checkpoint format. |
| **Determinism** | Research + harness design only | 100% confirmed empirically | 5 full scoring runs produced bit-identical output. Exceeds the >99% target for Phase 2 entry. |
| **Milestone 0.4 (Geolocation)** | MaxMind + ASN setup | Complete — pyasn for ASN, DB-IP Lite for country-level geolocation | ASN data is public/publishable (IPFS). Geolocation uses DB-IP Lite (CC BY 4.0, freely publishable). MaxMind dropped from the scoring pipeline — its EULA prohibits republishing derived data, which conflicts with IPFS audit trail publication and Phase 2 reproducibility (validators would each need a MaxMind license). |
| **VL `effective` timestamp lookahead** | Not specified; generator initially omitted the optional `effective` field, causing immediate activation on fetch | Adopted as a first-class mechanism in M1.10.6 with parameterized lookahead (0 for parity, 0.12 h for devnet, 0.5 h for testnet, caller-specified for admin overrides; service default remains 1 h) | Without lookahead, validators transition UNLs at slightly different wall-clock times based on their independent 5-minute HTTP poll cycles, creating a fork-risk propagation window. `ValidatorList.cpp:1406-1448` and `:1946-2003` already implement the pending-blob rotation; we just need to use it. Collapses the propagation window to sub-second consensus precision. |
| **Testnet VL transition mechanism** | Original plan anticipated shipping a postfiatd release with a new publisher key and URL, with a waiting window for community validators to upgrade | Publisher-key continuity: the scoring service reuses the existing `ED3F1E…` master key; the transition is a content overwrite at the existing `postfiat.org/testnet_vl.json` URL; no community validator configuration change is required | Minimises community operator friction and eliminates the silent-rejection failure mode that a key rotation would have created. Postfiatd's unknown-publisher-key behavior (untrusted rejection with no loud error) makes non-coordinated key changes operationally hazardous on a ~40-validator network. |
| **Admin override endpoints** | Not in the original plan | Added as M1.11 — two admin-guarded endpoints on the scoring service (`publish-unl/custom`, `publish-unl/from-round/{round_id}`) | Provides an auditable kill-switch path for Phase 1 and Phase 2 where the foundation's UNL is authoritative. Scheduled for removal at the Phase 3 boundary when validators produce the UNL via commit-reveal. |
| **VL distribution to `postfiat.org`** | Original plan assumed the scoring service's own `/vl.json` endpoint (at `scoring-{env}.postfiat.org/vl.json`) would be the authoritative source validators point at | Validators continue to read from the existing `postfiat.org/testnet_vl.json` (and a new `postfiat.org/devnet_vl.json`), both served by GitHub Pages from `postfiatorg/postfiatorg.github.io`. The scoring service pushes each round's signed VL into that repository via the GitHub Contents API, in a new orchestrator stage `VL_DISTRIBUTED` (M1.10.7) between `IPFS_PUBLISHED` and `ONCHAIN_PUBLISHED` | Preserves the existing URL every testnet community validator already trusts, avoids any operator configuration change, and mirrors the proxy-free publication pattern across devnet and testnet. The scoring-native endpoint `scoring-{env}.postfiat.org/vl.json` remains available for tooling and debugging, but is no longer the source validators consume. |

---

## Overview

```
Phase 0        Phase 1          Phase 2          Model Governance       Phase 3A
Research       Foundation       Shadow           Judge/model            Authority
Validation     Scoring          Verification     decision               Transfer

~1 week        ~4-6 weeks       ~7-9 weeks       ~2-4 weeks             ~2-3 weeks

┌──────────┐   ┌────────────┐   ┌────────────┐   ┌─────────────────┐   ┌────────────┐
│Model     │   │Evidence    │   │Frozen      │   │Benchmark repo   │   │Converged   │
│selection │──►│collection  │──►│artifacts   │──►│Deterministic    │──►│validator   │
│GPU setup │   │LLM scoring │   │Sidecars    │   │judge execution  │   │VL content  │
│Determin. │   │VL publish  │   │Commit/rev. │   │Upgrade plan     │   │transfers   │
└──────────┘   └────────────┘   └────────────┘   └─────────────────┘   └────────────┘
      │              │                │                    │                 │
      ▼              ▼                ▼                    ▼                 ▼
 Go/No-Go       Phase 1 stable   Convergence         Model/judge       Dynamic UNL
 on local       on testnet       proven              selected          authority
 inference                                             transparently     transferred

Optional Phase 3 Research branches from the Phase 2 and Model Governance results
if proof-of-logits or sampled-logit verification is worth the added complexity.
```

**Total estimated time through authority transfer:** ~16-23 weeks (4-5.5 months), plus optional Phase 3 Research if pursued.

---

## Repositories

| Repository | Language | Purpose | Created In |
|---|---|---|---|
| `postfiatd` (existing) | C++ | Existing validator-list consumer; no Phase 2 node-side work planned | — |
| `dynamic-unl-scoring` (new) | Python (FastAPI) | Scoring pipeline: data collection, LLM inference, VL generation, IPFS, on-chain | Phase 1 |
| `validator-scoring-sidecar` (new) | Python | Validator sidecar: artifact monitoring, scoring, commit-reveal, convergence participation | Phase 2 |
| Public benchmark/judge repo (new, name TBD) | Python/docs | Benchmark data, deterministic judge execution, candidate model evaluation, selection rationale | Model Governance |

---

## Infrastructure

### Instances (Vultr)

```
┌────────────────────────────────────────────────────────────────────┐
│                         DEVNET ENVIRONMENT                         │
│                                                                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                  │
│  │ Validator 1 │ │ Validator 2 │ │ Validator 3 │                  │
│  │  (existing) │ │  (existing) │ │  (existing) │                  │
│  └─────────────┘ └─────────────┘ └─────────────┘                  │
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
│  │(3 active PF)│ │VHS inventory│           │             │         │
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
│  │  Model: Qwen/Qwen3.6-27B-FP8                                │  │
│  │  Backend: pinned SGLang nightly, deterministic inference     │  │
│  │  GPU: H100, single GPU (TP=1)                                │  │
│  │  Pay-per-use: active GPU seconds | $0 idle (scale to zero)   │  │
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
5. **Environment variables**: PFTL RPC URL, wallet secret, VHS URL, IPFS credentials, Modal endpoint and proxy auth credentials, IPFS gateway URL
6. **Caddy config**: Reverse proxy to the FastAPI service on port 8000, auto-TLS via Let's Encrypt
7. **Monitoring**: Basic health check endpoint, log rotation, optional uptime monitoring

### Modal Serverless Setup

Deployment script: `infra/deploy_qwen36_endpoint.py`. Shared Modal/SGLang logic lives in `infra/deploy_endpoint.py`. See `phase0/docs/DeployQwen36_27B.md` for full details.

```bash
modal deploy infra/deploy_qwen36_endpoint.py
```

Configuration is in the deployment script via environment variable defaults. Key settings: H100, FP8 checkpoint auto-detected by SGLang, pinned SGLang nightly image, `--reasoning-parser qwen3`, `--mem-fraction-static 0.75`, `--chunked-prefill-size 4096`, `--max-running-requests 1`, `--enable-deterministic-inference`, and DeepGEMM pre-compiled on H100.

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

**Duration:** ~2-3 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** None | **Status:** Complete

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

**Duration:** ~1-2 days | **Difficulty:** ★★☆☆☆ Easy | **Dependencies:** Milestone 0.1 (model selected) | **Status:** Complete

**Goal:** Set up the Modal serverless endpoint with the selected model and verify it works end-to-end.

**Steps:**

**0.2.1 — Create Modal account and billing** ✅ (1 hour)
- Sign up at modal.com
- Add payment method
- Note: Modal charges per second of active GPU time, no charge when idle

**0.2.2 — Deploy serverless endpoint** ✅ (2-4 hours)
- Deployed the historical Phase 0 baseline via `modal deploy infra/deploy_qwen3_next_endpoint.py`
- Configure: SGLang backend, FP8 quantization, `--enable-deterministic-inference`
- Key settings: `--mem-fraction-static 0.75`, `--chunked-prefill-size 4096`, DeepGEMM pre-compiled
- Deploy and wait for the endpoint to become active

**0.2.3 — Test the endpoint** ✅ (2-4 hours)
- Test with curl against the OpenAI-compatible API:
  ```bash
  curl -X POST "<MODAL_ENDPOINT_URL>/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Modal-Key: <MODAL_KEY>" \
    -H "Modal-Secret: <MODAL_SECRET>" \
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

**Duration:** ~3 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestone 0.1 (model selected) | **Status:** Complete

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

**Duration:** ~1 day | **Difficulty:** ★☆☆☆☆ Trivial | **Dependencies:** None | **Status:** Complete

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
| Open-weight model selected that produces acceptable scoring quality | Yes | Done — Qwen3-Next selected in Phase 0; Qwen3.6 selected as active scorer after re-evaluation |
| GPU endpoint active and tested (SGLang backend) | Yes | Done — Modal, single H200 for Phase 0 baseline; active Qwen3.6 profile uses H100 |
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
| `RUNPOD_*` env vars | `MODAL_ENDPOINT_URL`, `MODAL_KEY`, `MODAL_SECRET` | RunPod was dropped in Phase 0 in favor of Modal; the active Modal endpoint is protected with proxy auth |

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
  MODAL_KEY
  MODAL_SECRET

  # IPFS
  IPFS_API_URL, IPFS_GATEWAY_URL

  # Scoring
  SCORING_CADENCE_HOURS (default: 168 = weekly)
  SCORING_MODEL_ID, SCORING_MODEL_NAME, SCORING_DISABLE_THINKING

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
| `MODAL_ENDPOINT_URL` | Qwen3.6 Modal LLM endpoint |
| `MODAL_KEY` | Modal Proxy Auth token ID for the scoring endpoint |
| `MODAL_SECRET` | Modal Proxy Auth token secret for the scoring endpoint |
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
  3. If the number of validators above cutoff is <= configured max (`UNL_MAX_SIZE`) → all are on the UNL
  4. If the number above cutoff exceeds `UNL_MAX_SIZE` → take the top validators by score up to that cap
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
- UNL inclusion logic with configurable threshold, max size, and minimum score gap for replacement
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
- **Validator manifests:** Fetched from the RPC node's `manifest` command (one call per selected UNL validator, up to configured `UNL_MAX_SIZE`; current deployments use 3 on devnet and 20 on testnet). VHS does not return the raw base64 manifest blob needed for VL assembly. Requires new `RPC_URL` config setting pointing to the environment's RPC node.
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
- Transition sequence is codified in M1.13: deploy the scoring service to testnet with `UNL_MAX_SIZE=20` and `VL_EFFECTIVE_LOOKAHEAD_HOURS=0.5`, let the first live round complete, then promptly publish a second live round inside the 30-minute lookahead so validators see a strictly higher sequence. The service delivers the content at the existing URL (`postfiat.org/testnet_vl.json`) via the Pages publisher built in M1.10.7 (GitHub Contents API push to `postfiatorg/postfiatorg.github.io/content/testnet_vl.json`). The scoring service continues to serve a parallel copy at `scoring-testnet.postfiat.org/vl.json` for tooling that prefers the scoring-native domain, but validators consume only the Pages URL.
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
  ├── snapshot.json           # Normalized validator evidence used to render the prompt
  ├── raw/                    # Raw API responses (verifiable audit trail)
  │   ├── vhs_validators.json # Raw VHS response, timestamped
  │   ├── vhs_topology.json   # Raw VHS topology response
  │   ├── crawl_probes.json   # Raw /crawl responses (IP resolution evidence)
  │   ├── asn_lookups.json    # Raw ASN lookup responses
  │   └── geoip_lookups.json  # Raw DB-IP country lookups
  ├── scoring_config.json     # Model version, weight hash, prompt version, parameters
  ├── prompt.json             # Exact OpenAI-compatible messages sent to the model
  ├── validator_id_map.json   # Anonymous prompt IDs mapped to validator public keys
  ├── raw_response.json       # Raw unparsed model response
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

**Goal:** Publish a scoring round receipt on-chain as a memo transaction. The final bundle CID in the memo is the integrity anchor — it is a content-addressed hash of the full audit trail, so anyone can fetch and verify the evidence independently.

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
    "final_bundle_cid": "Qm...",
    "round_number": 42,
    "vl_sequence": 42
  }
  ```
  The final bundle CID is the integrity anchor — all round details (scores, model, prompt version, validators) are in the audit trail reachable via the CID
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
  snapshot_hash, final_bundle_cid, onchain_tx_hash, vl_sequence,
  started_at, completed_at, error_message,
  state_transitions (JSONB array of {state, timestamp, result})
  ```
- Every state transition is logged for audit
- **Capabilities:**
  - `dry_run` — run the full pipeline without publishing (no IPFS pin, no on-chain memo, no VL upload)

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

**1.9.4 — Status API** ✅ (0.5 day)
- `GET /api/scoring/rounds` — list recent rounds with status and current state
- `GET /api/scoring/rounds/<id>` — detailed round info (all hashes, CIDs, timestamps, state transition log)
- `GET /api/scoring/unl/current` — current active UNL (latest successful round)

**Deliverables:**
- `ScoringOrchestrator` as a state machine with idempotent steps
- dry_run capability
- Postgres-based scheduling with advisory locks
- Manual trigger + status API endpoints
- Round tracking with state transition audit log

---

### Milestone 1.10: Devnet Testing & Validation

**Duration:** ~13-19 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.2, 1.9 | **Status:** Complete

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
  - `MODAL_ENDPOINT_URL`, `MODAL_KEY`, `MODAL_SECRET` — protected Qwen3.6 LLM scoring endpoint and Modal proxy auth credentials
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
- **Automated scheduler rounds:** use the configured `VL_EFFECTIVE_LOOKAHEAD_HOURS` (currently 0.12 hours on devnet and 0.5 hours on testnet; service default is 1 hour). Both deployed values are longer than the 5-minute poll interval and the 30-second error-retry interval, so every validator has multiple opportunities to fetch the pending blob before activation.
- **M1.10.8 parity transition VL:** lookahead **must be 0** (immediate activation). Validators are migrating from the static `[validators]` block to the URL mechanism with no cached VL state; if the first VL they fetch is pending, they have no trusted set and consensus stalls until the scheduled activation.
- **Admin override endpoints (M1.11):** accept an optional `effective_lookahead_hours` parameter, defaulting to the environment's configured `VL_EFFECTIVE_LOOKAHEAD_HOURS`, with 0 permitted for true-emergency immediate activation.
- **First testnet live sequence (M1.13):** use the configured 0.5-hour lookahead and publish a second, strictly higher sequence inside that window so existing validators move only to the newer blob.

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
- `GITHUB_PAGES_FILE_PATH` — `content/devnet_vl.json` for devnet, `content/testnet_vl.json` for testnet.
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

*Switch to automated scoring:* Enable the built-in scheduler (or trigger a manual automated round via `POST /api/scoring/trigger` without any override) so the next round runs the full pipeline end-to-end: data collection, LLM scoring, UNL selection with `UNL_MAX_SIZE=3`, VL signing with the configured 0.12-hour `effective_lookahead_hours`, IPFS publication, Pages distribution, and on-chain memo.

*Observe propagation and activation:*
1. Within ~2 minutes of Pages distribution, `https://postfiat.org/devnet_vl.json` returns the new VL.
2. Within 5-10 minutes of the Pages commit (each validator's default poll interval is 5 minutes), confirm via log inspection (`docker logs` on each validator) that every devnet validator has fetched the new VL and logged the pending blob being held for activation (rippled emits `ValidatorList::verify` decision logs at this point).
3. At the scheduled activation time (T + 0.12 hours), every validator's `updateTrusted` rotates the pending blob to current simultaneously. Verify all 6 validators transition on the same ledger close.
4. After activation, consensus is governed by the 3 validators selected by the scoring service. Confirm the 3 selected validators are producing validations that reach quorum, and the other 3 (the dropped incumbent plus the two newcomers that weren't selected) continue running but are no longer counted toward quorum.

*Important limitation:* With `UNL_MAX_SIZE=3`, the network requires all 3 selected validators to agree (ceil(3 × 0.8) = 3). There is zero fault tolerance — if any one of the 3 goes down, the network stalls until it comes back. This is accepted for devnet testing. Testnet runs with `UNL_MAX_SIZE=20`, giving materially more headroom while keeping the initial dynamic trust set smaller than the full eligible validator set.

**1.10.10 — Prompt iteration and scoring review** ✅ (2-3 days)
- Analyze completed normal devnet rounds produced by the active Qwen3.6 scorer. Verify inclusion by `scoring_config.json` (`model_id = Qwen/Qwen3.6-27B-FP8`) rather than by date alone; exclude failed and override-only rounds.
- Review the published artifacts for those rounds (`raw_response.json`, `scores.json`, `unl.json`, `snapshot.json`, `prompt.json`, `validator_id_map.json`, `scoring_config.json`).
- Review LLM scoring output quality:
  - Are scores differentiated? (not all clustered at 85-90)
  - Does reasoning reference actual validator metrics (agreement %, version, geography)?
  - Does the LLM correctly penalize missing domain attestation?
  - Does geographic diversity factor into scoring? (validators in different countries/ASNs should contribute to network diversity)
  - Does the LLM correctly identify and penalize older software versions?
- Compare validator ranking and UNL selection over time; confirm high-ranked validators stay high for understandable reasons and score changes map to real evidence changes.
- Iterate on the prompt based on output quality
- If the prompt changes scoring behavior, create a new versioned prompt file (for example `prompts/scoring_v3.txt`) and publish the matching prompt version in round artifacts. Keep older prompt files for audit history.
- Finalize prompt version
- Outcome documented in `docs/phase 1/M1.10.10_Qwen36DevnetScoringReview.md`; active prompt advanced to `prompts/scoring_v3.txt`.

**1.10.11 — Scoring stability testing** ✅ (1-2 days)
- Compare repeated manual/scheduled devnet scoring rounds on a stable validator set — scores and UNL membership should be stable enough for the configured churn controls
- One-candidate-added / one-candidate-removed test — existing validator scores should not shift significantly when an unrelated validator is added or removed from the snapshot
- Measure natural score variance across rounds to calibrate the minimum score gap config value for churn control
- Validate that the churn control mechanism behaves as expected: borderline validators should not oscillate between rounds

**1.10.12 — Edge case testing** ✅ (1-2 days)
- Test: what happens when VHS is down? (data collection should fail gracefully, round marked FAILED)
- Test: what happens when Modal cold-starts? (should wait — 35-min startup timeout configured)
- Test: what happens when IPFS is unreachable? (round should fail gracefully)
- Test: what happens when the GitHub Pages PUT fails (rate limit, bad token, SHA conflict)? (`VL_DISTRIBUTED` retries with backoff; persistent failure marks round FAILED without spending an on-chain memo)
- Test: what happens when PFTL node is down? (after public VL publication, memo submission failure should produce `VL_PUBLISHED_MEMO_FAILED` with an operator-visible warning)
- Test: what happens with 0 validators in VHS? (should produce empty UNL, not crash)
- Test: scheduler runs correctly at configured interval

**Deliverables:**
- 6 devnet validators with organic diversity (geography, ASN, domain, software version, agreement history)
- Multiple successful scoring rounds with differentiated scores
- Effective-timestamp lookahead mechanism implemented and verified end-to-end via devnet validator log inspection
- GitHub Pages publisher pushing VLs to `postfiatorg/postfiatorg.github.io` for devnet, with the `VL_DISTRIBUTED` orchestrator stage integrated
- All 6 devnet validators fetching dynamic VL from `postfiat.org/devnet_vl.json` (UNL_MAX_SIZE=3), with parity and dynamic-switch transitions executed as distinct steps
- Finalized scoring prompt
- Prompt-review findings documented
- Edge case test results documented

---

### Milestone 1.11: Admin Override Endpoints

**Duration:** ~3-5 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.10.6 (effective-timestamp lookahead) and 1.10.7 (VL distribution to Pages) | **Status:** Complete | **Goal:** Provide an auditable kill-switch surface on the scoring service that lets the operator publish a specific UNL without running the automated pipeline. Required before M1.10.8 (devnet parity uses the custom endpoint to publish the seed VL) and before M1.13 so the foundation has a rehearsed emergency path ready when testnet flips live. These endpoints are temporary scaffolding for Phase 1 and Phase 2; they are removed at the Phase 3 boundary when validators begin producing the UNL via commit-reveal and the foundation is no longer the sole publisher.

**Why two endpoints:** Audit-trail clarity. The "republish arbitrary set" path and the "republish historical round" path serve different operational intents and should be distinguishable in the audit record without a post-hoc reason parse.

**Steps:**

**1.11.1 — Endpoint design and schema updates** ✅ (~0.5 day)

- Add `override_type` (nullable text: `"custom"` or `"rollback"`) and `override_reason` (nullable text) columns to the `scoring_rounds` table via a new numbered migration under `migrations/`.
- Define the request/response contracts:
  - `POST /api/scoring/admin/publish-unl/custom` — body: `{master_keys: [nHU...], reason: string, effective_lookahead_hours?: number (default VL_EFFECTIVE_LOOKAHEAD_HOURS), expiration_days?: number (default VL_EXPIRATION_DAYS)}`. Validates that every master key has a cached manifest (fetches from the RPC node if missing).
  - `POST /api/scoring/admin/publish-unl/from-round/{round_id}` — body: `{reason: string, effective_lookahead_hours?: number (default VL_EFFECTIVE_LOOKAHEAD_HOURS), expiration_days?: number (default VL_EXPIRATION_DAYS)}`. Reads the selected UNL artifact for the referenced round and republishes that UNL, with historical fallback for old flat bundles.
- Both endpoints require `X-API-Key: <ADMIN_API_KEY>` (reuse the existing admin auth in `scoring_service/api/scoring.py`).
- Both return `202 Accepted` with the synthetic round number; publishing runs in a background thread like the existing manual trigger.

**1.11.2 — Implementation** ✅ (~1-2 days)

- New handlers in `scoring_service/api/scoring.py` that acquire the same advisory lock (`99001`) as the automated path so overrides never race the scheduler.
- New orchestrator entry points that skip COLLECTING, SCORED, and SELECTED stages but go through VL_SIGNED, IPFS_PUBLISHED, VL_DISTRIBUTED, and ONCHAIN_PUBLISHED identically to automated rounds. The override round writes the selected UNL, signed VL, bundle index, and execution manifest through the same artifact publisher used by automated rounds, pushes the signed VL to `postfiatorg.github.io` through the same Pages publisher, and emits an on-chain memo with a distinct type string `pf_dynamic_unl_override` so explorers and downstream consumers can distinguish manual republishes from automated rounds.
- As part of this work, extend the standard (non-override) memo payload emitted by `scoring_service/services/onchain_publisher.py` to include `round_number` alongside the final bundle CID and `vl_sequence` fields. The field makes the memo self-describing for the common "I saw this memo, show me the round" workflow without requiring a downstream `vl_sequence` → `round_number` DB lookup, and costs effectively nothing in memo size. Override memos inherit the same shape with the distinct type string set.
- Store the synthetic round with `override_type` and `override_reason` populated. Set the seven-stage status to `COMPLETE` so round queries return normally.
- Preserve the VL sequence reserve/confirm/release contract: the override acquires the next sequence from `vl_sequence`, and on failure the sequence is released exactly as in the automated path.

**1.11.3 — Tests** ✅ (~1 day)

- Unit tests covering both endpoints: auth rejection without the admin key, validation failures (unknown master key, missing reason, invalid `round_id`), concurrency collision with the advisory lock, full success path with mocked downstream clients.
- End-to-end test: against a real devnet deployment, trigger a `custom` publish with the current UNL and a `rollback` publish against an earlier round. Verify the IPFS audit trail directory is written, the on-chain memo uses the override type, and the explorer round-query endpoint returns the synthetic round with the override flag.

**1.11.4 — Documentation** ✅ (~0.5 day)

- Extend `docs/ScoringOperations.md` with runbooks for both override scenarios (see the Operations guide updates section of this milestone in `docs/ScoringOperations.md`).
- Add a bullet to `docs/phase 1/M1.11_ExplorerScoringUI.md`'s status-badge table (if relevant) or note in the audit-trail panel design that override rounds render with a distinct marker.

**1.11.5 — Dry-run exercise on devnet** ✅ (~0.5 day)

- Before declaring Phase 1 complete, invoke each endpoint against the devnet deployment at least once with a plausible but non-disruptive payload (custom: the current UNL; rollback: a previous completed round). Confirm the VL is signed and served at `/vl.json`, the audit trail is pinned to IPFS, and the on-chain memo is submitted with the override type.

**Deliverables:**
- Two admin-guarded override endpoints (`publish-unl/custom`, `publish-unl/from-round/{round_id}`) routed through the existing sequence, audit-trail, and memo machinery
- Database schema updated with `override_type` and `override_reason` columns on `scoring_rounds`
- Test coverage including an end-to-end exercise against devnet
- Operational runbooks in `docs/ScoringOperations.md`
- Explicit removal note tying these endpoints to the Phase 3 authority-transfer boundary

---

### Milestone 1.12: Explorer Scoring Pages

**Duration:** ~9-14 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 1.10.5 (first scoring round producing real data) | **Status:** Complete | **Parallel with:** M1.10.10+

**Design reference:** `docs/phase 1/M1.11_ExplorerScoringUI.md` — full information architecture, page mockups, state taxonomy, routing, caching, loading/error/empty-state taxonomy, accessibility, mobile, and per-section data-source map. The filename reads `M1.11_` for historical reasons (the scope was renumbered to M1.12 when admin overrides became M1.11); the milestone is M1.12. Read that document before implementation; this milestone section tracks scope and sequencing only.

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
- `llm_endpoint`: derived from the most recent round — unhealthy only when status is FAILED, `snapshot_hash` and `input_package_cid` are set, and `scores_hash` is null (the "failed after input freeze but before scoring completed" heuristic)
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
- **Failed-at-stage derivation** (no explicit stage field exists on the round record): for FAILED rounds the stage label surfaced in the tooltip is derived client-side from which of the round's `*_hash` / `*_sequence` / `*_cid` fields are populated — the first missing one in pipeline order (`snapshot_hash` → `input_package_cid` → `scores_hash` → `vl_sequence` → `final_bundle_cid` → `github_pages_commit_url` → `memo_tx_hash`) names the stage. Matches the heuristic already used by the pipeline-health endpoint.
- **Navigation state**: clicking an arrow or a strip glyph switches a local `viewingRoundNumber` React state. The ranked validator table and the audit trail panel both re-render for the selected round. The URL does not change in this milestone — URL-driven deep-linking is M1.12.11. When a new round completes in the background (observed via the existing `latestAttempt` refetch on `/api/scoring/rounds?limit=1`), the nav auto-advances to the newer round **only if** the user has not explicitly selected a non-latest round; explicit selections are sticky until the user clicks `Next ▶` back to latest. The header banner (Last round / Next round in / Health cards) stays locked to the actual latest-pipeline-round state regardless of navigation — the banner describes the pipeline, the nav strip describes what the user is looking at.
- **Audit trail panel** placed below the ranked validator table. Surfaces the verification chain for the currently-viewed round:
  - **Final bundle CID** with a copy button plus two gateway links named by literal hostname (`Open on ipfs-{env}.postfiat.org`, `Open on Pinata gateway`). Per-environment hostname derived from `VITE_ENVIRONMENT`.
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

**1.12.13 — Accessibility + mobile** ✅ (~1 day)
- Status states use distinct glyphs (`● ◐ ○ —`), not color alone; glyphs render as actual characters
- Interactive elements keyboard-accessible with visible focus rings; color contrast WCAG AA on bars and badges
- Mobile: ranked table's 5 dimension columns collapse into a single `Details ▼` cell that expands inline on tap; Rank, Validator, Overall, Δ, Details remain visible
- Validators page three Agreement columns may collapse per existing responsive rules; Validator detail Scoring section stacks to single column
- Mobile layout verified on devnet before deploy, not deferred to polish

**1.12.14 — Polish + deploy** ✅ (~0.5-1 day)
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

**Duration:** ~1-2 weeks elapsed (of which ~1-2 days active engineering, the rest monitoring) | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestones 1.10, 1.11 | **Status:** Complete

**Goal:** Deploy the scoring pipeline to testnet and transition up to 20 selected validators from the full testnet validator set to the dynamically generated VL without requiring any community validator to change their configuration.

**Publisher-key continuity:** Testnet validators' `validators-testnet.txt` already points at `https://postfiat.org/testnet_vl.json` signed by publisher key `ED3F1E0DA736FCF99BE2880A60DBD470715C0E04DD793FB862236B070571FC09E2`. The scoring service reuses this exact master key and signing manifest, so the transition is a URL-content overwrite, not a trust-root rotation. Community validators need no config change, no restart, and no coordination. This removes the only meaningful source of operator friction from the transition. (Custody: the key is held by the foundation's blockchain engineer and a second principal; neither holder should ship the key onto any system outside the scoring service's secret store, and the previous publishing location should cease signing once parity is confirmed.)

**Steps:**

**1.13.1 — Testnet deployment configuration** ✅ (~0.5 day)

- Deploy the scoring service to testnet via the existing `deploy-testnet.yml` workflow with the scheduler enabled.
- Required testnet runtime values:
  - `SCORING_CADENCE_HOURS=168`
  - `VL_EFFECTIVE_LOOKAHEAD_HOURS=0.5`
  - `UNL_MAX_SIZE=20`
  - `RPC_URL=https://rpc.testnet.postfiat.org`
  - `ADMIN_API_KEY=${TESTNET_ADMIN_API_KEY}`
- Confirm the testnet explorer branch has the UNL Scoring proxy/API changes deployed before relying on the explorer page for inspection.
- Optional dry-runs are useful for checking score output, but `dry_run=true` stops after UNL selection and does not sign, publish, write Pages content, or produce the full VL audit trail.

**1.13.2 — Pre-activation review** ✅ (~0.5 day)

- Pre-activation criteria:
  - GitHub Actions secrets for testnet are present, including `TESTNET_ADMIN_API_KEY`, `TESTNET_VL_PUBLISHER_TOKEN`, `TESTNET_GITHUB_PAGES_TOKEN`, `TESTNET_PFTL_WALLET_SECRET`, `TESTNET_PFTL_MEMO_DESTINATION`, and `TESTNET_DB_PASSWORD`.
  - The current canonical testnet VL sequence at `https://postfiat.org/testnet_vl.json` is recorded before publishing begins.
  - The admin trigger endpoint accepts `X-API-Key: <TESTNET_ADMIN_API_KEY>`.
  - Manual rollback path is ready: publish a known-good custom UNL or set the UNL manually if the dynamic selection is wrong.
- If any criterion fails, fix deployment/configuration before allowing a live round to publish.

**1.13.3 — Initial live scoring sequence** ✅ (~1 day)

- Let the first scheduled live round run after deployment, or trigger it manually via `POST /api/scoring/trigger`. It uses the configured 0.5-hour lookahead and writes the signed VL to `https://postfiat.org/testnet_vl.json`.
- The current pre-transition testnet VL is already sequence 1, so the first scoring-service sequence 1 publication is a bootstrap/audit round for existing validators rather than the transition round. Existing validators should not accept it as newer because the sequence is not strictly higher.
- Promptly trigger a second normal scoring round inside the 30-minute lookahead window. This publishes a strictly higher sequence, giving validators a pending blob they can fetch and activate simultaneously when `closeTime >= effective`.
- During the 30-minute window, inspect the VL contents, audit trail, and on-chain memo. If anything is wrong, publish a known-good override with a higher sequence and `effective_lookahead_hours=0`, or manually set the UNL.

**1.13.4 — Content delivery to the existing VL URL** ✅ (~0.5 day)

- Option A is the chosen transition mechanism: the scoring service's signed VL overwrites the content at `https://postfiat.org/testnet_vl.json` via the Pages publisher built in M1.10.7. Configure the testnet deployment of the scoring service with `GITHUB_PAGES_FILE_PATH=content/testnet_vl.json`, `GITHUB_PAGES_REPO=postfiatorg/postfiatorg.github.io`, and a dedicated `TESTNET_GITHUB_PAGES_TOKEN` (separate PAT from devnet — same service account, separate secret for least-privilege cross-environment isolation).
- GitHub Pages atomicity: the Contents API replaces the file in a single commit, and the Pages build serves either the previous commit or the new commit, never a partially-written file.
- The scoring service continues to also serve its own copy at `https://scoring-testnet.postfiat.org/vl.json` for tooling that prefers the scoring-native domain. Validators do not consume this endpoint; they consume `postfiat.org/testnet_vl.json` exclusively.

**1.13.5 — Monitoring and stabilization** ✅ (~1-2 weeks elapsed, ~1-2 days active)

- Run 2-3 weekly scoring rounds post-go-live with the configured 0.5-hour `effective_lookahead_hours`.
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
| Scoring pipeline running stable on testnet for 2+ weeks | Yes | Done |
| All testnet validators consuming dynamic VL | Yes | Done |
| No consensus disruptions from VL transitions | Yes | Done |
| Scoring quality reviewed and acceptable | Yes | Done |
| Audit trail published to IPFS and verifiable | Yes | Done |
| On-chain memo publication working | Yes | Done |
| Effective-timestamp lookahead mechanism in use on both devnet and testnet | Yes | Done |
| GitHub Pages publisher pushing VLs to `postfiatorg/postfiatorg.github.io` for both devnet (`content/devnet_vl.json`) and testnet (`content/testnet_vl.json`) deployments | Yes | Done |
| Admin override endpoints (custom and from-round) exercised end-to-end against a non-production deployment | Yes | Done |
| Determinism research complete (Milestone 0.3) | Yes | Done |
| Reproducibility harness built and run — >99% output equality on mandatory GPU type | Yes | Done |
| Mandatory GPU type selected for Phase 2 | Yes | Done |

---

### Operational Safety Notes (Phase 1)

The Phase 1 rollout relies on properties of postfiatd's existing validator-list consumption path that are not always obvious to readers of this roadmap. These notes capture the load-bearing ones so future operators and reviewers understand why specific parameters are set where they are.

**VL polling is HTTP-only and independent of consensus events.** `ValidatorSite::onTimer` schedules refresh fetches on a per-site `boost::asio` timer with a default interval of 5 minutes (clamped between 1 minute and 1 day, optionally overridden per-response by a `refreshInterval` field). Flag ledgers (every 256 ledgers) are used for amendment and fee voting only — `isFlagLedger` is never referenced by VL code. No postfiatd C++ change, no amendment, and no on-chain event is required for validators to begin consuming the scoring service's VLs.

**VL activation is synchronized via the `effective` field, not the fetch time.** When a v2 blob carries `effective > closeTime`, postfiatd holds it in `remaining` and promotes it to `current` only when `closeTime >= effective`. Publishing with a lookahead (see M1.10.6) allows every validator to fetch the pending blob in advance and transition in unison on the same ledger close. The current testnet deployment uses 0.5 hours, which is long enough for GitHub Pages propagation and several 5-minute validator polls without delaying applied UNL changes unnecessarily.

**An expired VL does not silently fall back to `[validators]`.** When the current VL's `validUntil` has passed and no new blob has arrived, postfiatd calls `setUNLBlocked()` and halts consensus, serving `warnRPC_EXPIRED_VALIDATOR_LIST` on RPC responses. The local `[validators]` list, if present, is additive rather than a fallback — trust requires `keyListings_[key] >= listThreshold_`. This is why the 500-day default `VL_EXPIRATION_DAYS` is a safety feature: it gives the scoring service a very large margin to recover from any outage before consensus is affected. Shortening it is not advised without a proportionally stronger availability guarantee for the scoring service.

**An unknown publisher key is rejected silently.** When a blob's publisher master key is not in a validator's configured `[validator_list_keys]`, postfiatd returns `untrusted` from `verify` without even checking the signature. There is no loud error. This is why publisher-key continuity is load-bearing for the testnet transition: rotating to a new key without first coordinating with every community operator would cause their validators to silently ignore subsequent VLs. Any future key rotation must use the multi-publisher mechanism (two keys in `[validator_list_keys]`, two blobs signed in parallel) with a long overlap window.

**Round-to-round UNL overlap is protected by churn control, not by the transition mechanism.** The XRPL pairwise-overlap safety bound derives from the 80% quorum requirement: for two validators with UNLs of size `n` and quorum `q = 0.8n` to simultaneously validate conflicting ledgers, some shared validators must vote for both (Byzantine behavior). Pigeonhole analysis yields a theoretical floor on overlap somewhat below 70% for symmetric UNLs with tolerable Byzantine faults; the XRPL operational convention is ≥90% for safety margin against transient Byzantine, offline, and partition conditions. With lookahead, all validators flip UNL simultaneously, so pairwise-overlap-between-validators stays at ~100% during transitions; the overlap concern reduces to round-to-round UNL content change, which `UNL_MIN_SCORE_GAP` (default 5) and incumbent stickiness in `unl_selector.py` keep well above 90% under normal scoring variance.

**GitHub Pages propagation is fast enough for the configured lookahead window.** Pages builds typically complete within 1-2 minutes of the Contents API commit. Because testnet rounds publish with 0.5 hours of effective lookahead, validators have roughly 28 minutes after a typical Pages build to poll and cache the pending blob before activation — well within the 5-minute default `refreshInterval`. The `VL_DISTRIBUTED` stage does not complete until the Contents API PUT returns successfully; transient 5xx or rate-limit failures are retried with exponential backoff, and persistent failure fails the round before any on-chain memo is spent. The `postfiat-scoring-bot` fine-grained PAT expires annually and must be rotated; rotation procedure is documented in `docs/ScoringOperations.md`.

---

## Phase 2: Validator Shadow Verification

**Duration:** ~7-9 weeks | **Difficulty:** ★★★★★ Very Hard

**Goal:** Let validators independently verify foundation scoring rounds in shadow mode. The foundation scoring service continues to collect evidence, score rounds, select the canonical UNL, sign validator lists, and publish the authoritative VL. Validator sidecars score the same frozen round package, commit and reveal their outputs, and produce convergence evidence without changing consensus behavior.

```
Phase 1 complete: Foundation scoring service is authoritative
         |
         v
+------------------------------+
| Freeze scoring input package |
| Evidence + request + runtime |
| manifest only                |
+------------------------------+
         |
         v
+------------------------------+
| Expose frozen input package  |
| Validators detect new round  |
+------------------------------+
         |
         v
+------------------------------+
| Validator sidecars score the |
| frozen input independently   |
+------------------------------+
         |
         v
+------------------------------+
| Commit salted output hashes  |
| Reveal output + salt later   |
+------------------------------+
         |
         v
+------------------------------+
| Foundation verifies reveals  |
| and publishes convergence    |
+------------------------------+
         |
         v
Phase 3 input: trusted evidence about validator-side convergence
```

**Important Phase 2 boundary:** Phase 2 does not transfer VL authority to validators and does not require node-side protocol changes. It proves whether independent validator operators can reproduce, inspect, and audit scoring rounds before any future authority-transfer work begins.

---

### Milestone 2.0: Verification Artifact Bundle and Execution Manifest

**Duration:** ~1 week | **Dependencies:** Phase 1 complete | **Status:** Complete

**Goal:** Restructure completed-round scoring artifacts so validator tooling can verify a final audit bundle from one clean, immutable package.

The final audit bundle contains everything a validator sidecar needs to reproduce the scoring decision for that round after foundation scoring has completed:

- Validator evidence gathered by the foundation scoring service.
- Prompt and message payloads used for the LLM scoring request.
- Runtime execution manifest covering model snapshot, tokenizer/config, SGLang image/version/arguments, GPU class expectations, request parameters, parser version, selector version, and canonical hash rules.
- Foundation raw outputs, parsed scores, selected UNL, signed VL output, and hashes that connect later publication receipts to the round.
- Explicit handling for override rounds where no LLM execution is expected.

The package is organized for machine validation first and human audit second. Existing Phase 1 CIDs remain historical audit records; Phase 2 rounds use the new verification-oriented bundle layout.

M2.0 publishes input files inside the final audit bundle after scoring, selection, and VL signing. It does not publish a separate input-only package before scoring. That pre-scoring package is the M2.1 `input_package_cid` work defined in [`docs/phase2/FrozenRoundBoundary.md`](phase2/FrozenRoundBoundary.md).

**Steps:**

**2.0.1 — Audit the current artifact bundle** ✅ (~0.5-1 day)
- Classify the current published files and capture the Phase 2 bundle direction in [`docs/phase2/ArtifactBundleAudit.md`](phase2/ArtifactBundleAudit.md).
- Use the audit as the source of truth for staged names, legacy-file treatment, and clean cutover expectations.

**2.0.2 — Define the execution manifest schema** ✅ (~1 day)
- Specify the model, runtime, request, parser, selector, code-version, and canonical-hash fields required for sidecar verification.
- Separate fields that are required for Phase 2 eligibility from optional fields that can be filled as runtime instrumentation improves.
- Include explicit no-inference semantics for override rounds so sidecars can verify them without expecting model execution.

**2.0.3 — Implement the staged bundle layout** ✅ (~1-2 days)
- Publish new scoring artifacts under clear `inputs/`, `runtime/`, `outputs/`, and `raw/` paths for normal rounds, private dry-runs, and no-inference override rounds.
- Generate `bundle.json` and `runtime/execution_manifest.json` from actual scoring-service and deployment metadata, including automatic code commit and model revision values where available.
- Prefer deploy-provided metadata for model revision and scoring-service commit, and defer a Modal runtime metadata endpoint unless implementation proves it is needed.
- Leave output comparison hashes and canonical verifier hash rules to M2.0.4 so this step stays focused on the bundle structure and execution contract.
- Update artifact consumers before the first changed scoring round so new bundles do not need to keep publishing old top-level names.
- Keep historical read support for existing immutable CIDs without rewriting old artifact bundles.

**2.0.4 — Add verification hashes and canonicalization rules** ✅ (~0.5-1 day)
- Define the hash targets a sidecar compares and use one canonical JSON encoding wherever validators compare bytes.
- Keep the canonical hash target stable across IPFS, HTTPS fallback, local verifier output, and future commit-reveal messages.

**2.0.5 — Document the verifier sequence and historical-round policy** ✅ (~0.5 day)
- Explain how to fetch, verify, and rerun a Phase 2-eligible bundle while treating existing Phase 1 CIDs as audit-only records in [`docs/phase2/BundleVerificationGuide.md`](phase2/BundleVerificationGuide.md).
- Make the first Phase 2-eligible round explicit so operators know where sidecar verification begins.

---

### Milestone 2.1: Frozen Input Package Lifecycle

**Duration:** ~1 week | **Dependencies:** M2.0 | **Status:** In Progress

**Goal:** Make each normal public scoring round operate from a frozen input package instead of live data that can drift during verification.

**Design reference:** [`docs/phase2/FrozenRoundBoundary.md`](phase2/FrozenRoundBoundary.md) defines the M2.1.1 input-freeze contract.

The foundation service should collect evidence, build the exact model request, freeze an immutable **input package**, and then require both the foundation scorer and future validator sidecars to score from that same package. Validators must score only the frozen artifact, not current VHS state, live crawler state, or changing network data.

M2.1 introduces two CIDs per normal public round:

- `input_package_cid` — new in M2.1. Contains only the immutable files required to reproduce the scoring input.
- `final_bundle_cid` — canonical M2.1 name for the final audit bundle CID stored in the scoring service database, API, orchestrator result, and current memo payload.

The input package must contain:

```text
bundle.json
inputs/validator_evidence.json
inputs/model_request.json
inputs/validator_map.json
runtime/execution_manifest.json
raw/vhs_validators.json
raw/vhs_topology.json
raw/crawl_probes.json
raw/asn_lookups.json
raw/geolocation_lookups.json
```

The final bundle remains self-contained. It should repeat the frozen input content files from `inputs/`, `runtime/`, and `raw/`, add the foundation outputs, and reference the input package CID/hash from its own final `bundle.json`:

```text
outputs/model_response.json
outputs/validator_scores.json
outputs/selected_unl.json
outputs/signed_validator_list.json
outputs/verification_hashes.json
```

Once an input package is frozen, it must never be mutated. If the input is wrong, the round fails or is superseded by a new round.

M2.1 does **not** implement the future on-chain round-announcement protocol. In M2.1, "announcement" only means the service exposes enough immutable discovery data for the later M2.2 protocol: network, round number, round kind, `input_package_cid`, `final_bundle_cid` when available, HTTPS fallback URL, and schema/version fields. M2.2 defines where and how that announcement is published, including any PFTL memo/event format and commit/reveal timing fields.

Compatibility note: downstream consumers should migrate round API, explorer UI,
ops scripts, and new memo parsing from `ipfs_cid` to `final_bundle_cid`.
Historical Phase 1 memos still contain `ipfs_cid`, so memo decoders should keep
that fallback only for historical reads.

Timing windows should remain configurable and be chosen from operational testing. The roadmap should not lock in exact 12-hour or 24-hour values until devnet shadow verification proves what is practical.

**Steps:**

**2.1.1 — Define the frozen input boundary** ✅ (~0.5-1 day)
- The freeze boundary is after evidence collection, prompt/model-request construction, validator-map construction, and execution-manifest construction, and before Modal scoring.
- Foundation outputs are not part of the input freeze. Their immutability remains implicit in the existing final IPFS bundle publication.
- Define the normal-round input package contract in [`docs/phase2/FrozenRoundBoundary.md`](phase2/FrozenRoundBoundary.md).
- Define how the final bundle references `input_package_cid` and repeats the frozen input content files so the final audit bundle remains self-contained.
- Make the boundary visible in persisted metadata so sidecars and operators can distinguish draft state from input-frozen state.

**2.1.2 — Implement the frozen input lifecycle** (~1-2 days)
- Add only one new round state for M2.1: `INPUT_FROZEN`.
- Create and pin a normal-round input package before Modal scoring. The package contains collected evidence, the exact model request, validator identity map, execution manifest, and raw source evidence, but no model responses, parsed scores, selected UNL, signed VL, or verification hashes.
- Store input package fallback files in a dedicated insert-only table so shared paths such as `bundle.json` and `inputs/model_request.json` cannot collide with final audit bundle fallback files or mutate after freeze.
- Persist `input_package_cid`, `input_package_hash`, and `input_frozen_at` atomically with the input fallback files, then transition the round to `INPUT_FROZEN`.
- Score from the frozen model request and validator map, not from a rebuilt live request.
- Expose input package metadata through public round metadata/API responses and serve frozen input fallback files under the `/input/` route namespace.
- Keep the final bundle self-contained by repeating the frozen input files, adding the foundation outputs, and recording the input package CID/hash/frozen timestamp in final `bundle.json`.
- Preserve dry-run privacy and admin override behavior; only normal public scoring rounds create frozen input packages.
- If collection or input-package creation fails before `INPUT_FROZEN`, mark the round `FAILED` with no input CID. If scoring or any later stage fails after `INPUT_FROZEN`, mark the round `FAILED` and retain the immutable input CID for audit/debugging.
- Do not add `ANNOUNCED`, `VERIFICATION_OPEN`, or `VERIFICATION_CLOSED` round states in M2.1. Represent those later as metadata/timestamps only if M2.2 needs them.

**2.1.3 — Keep announcement mechanics deferred to M2.2** (~0.5-1 day)
- M2.1 exposes enough immutable discovery data for later validator sidecars: network, round number, round kind, input package CID, input package hash/identifier, frozen timestamp, final bundle CID when available, and HTTPS fallback URLs.
- Defer the actual announcement transport, on-chain memo/event format, commit/reveal schedule fields, timing windows, and sidecar submission mechanics to M2.2.

---

### Milestone 2.2: Commit-Reveal Protocol

**Duration:** ~1 week | **Dependencies:** M2.0, M2.1 | **Status:** Not Started

**Goal:** Define the high-level memo flow and canonical commitment rules used by validator sidecars.

Phase 2 needs four conceptual memo/event types. M2.1 only creates and exposes the frozen input package metadata used by the first event; M2.2 defines the transport and validation rules for these events.

1. Round announcement: references the frozen artifact package and the commit/reveal schedule.
2. Validator commit: publishes a salted, domain-separated commitment bound to the round and validator identity.
3. Validator reveal: publishes or references the validator output plus salt so the commitment can be verified.
4. Convergence report: publishes the foundation comparison result after reveals are processed.

Commitments should be computed from canonical bytes, not loose string concatenation. The exact schema can be refined during implementation, but the protocol must prevent replay across rounds, validators, and environments.

**Steps:**

**2.2.1 — Define memo/event responsibilities** (~1 day)
- Specify the required round announcement, validator commit, validator reveal, and convergence report fields at a schema level.
- Keep memo schemas versioned and small enough to remain practical on-chain, with larger evidence referenced by CID or hash.

**2.2.2 — Define canonical commitment inputs** (~0.5-1 day)
- Choose the exact canonical output hash target, salt handling, domain separation, and replay-prevention fields.
- Bind commitments to network, round, validator identity, and bundle hash so they cannot be replayed in another context.

**2.2.3 — Define timing and validity rules** (~0.5-1 day)
- Document commit/reveal windows, late commits, missed reveals, duplicate submissions, and minimum data needed for a convergence report.
- Keep the timing configurable until devnet proves realistic windows for cold starts, model execution, and operator infrastructure.

**2.2.4 — Add protocol validation helpers** (~1-2 days)
- Implement shared validation logic or schemas so the foundation service and sidecar interpret memo payloads consistently.
- Validate version, network, round number, validator identity, hash length, salt shape, and referenced bundle/output hashes.

**2.2.5 — Document fallback behavior** (~0.5 day)
- State what happens when participation is low or divergent while foundation VL publication remains authoritative.
- Make clear that Phase 2 convergence evidence is observational and cannot block or replace canonical VL publication.

---

### Milestone 2.3: Validator Sidecar Repository

**Duration:** ~1 week | **Dependencies:** M2.0, M2.1, M2.2 | **Status:** Not Started

**Goal:** Create a separate validator-facing sidecar repository for shadow verification operations.

The sidecar repo should provide the convenience tooling a validator needs to participate:

- Cron or daemon mode that monitors for new frozen artifact announcements.
- Package download and validation.
- Scoring execution against the frozen package.
- Commit and reveal submission.
- Operator configuration, wallet setup, and clear runbooks.

The scripts are convenience tooling, not a trust requirement. A validator should be able to independently inspect the artifact package and reproduce the same steps manually if needed.

**Steps:**

**2.3.1 — Create the sidecar repository skeleton** (~0.5-1 day)
- Set up the validator-facing project structure, configuration pattern, basic CLI entrypoint, and development workflow.
- Keep sidecar runtime concerns separate from the foundation scoring service so validator operators can reason about their own deployment.

**2.3.2 — Implement artifact discovery and download** (~1-2 days)
- Fetch round announcements, download the referenced package, and verify bundle hashes before local execution.
- Cache verified packages safely so retries do not depend on mutable remote state or repeated gateway availability.

**2.3.3 — Add manual verification mode** (~1 day)
- Let operators run one round by CID or round number before enabling unattended daemon behavior.
- Print comparison results locally without requiring commit/reveal submission, so setup can be tested without chain side effects.

**2.3.4 — Add daemon mode and local state tracking** (~1-2 days)
- Track seen rounds, current participation state, retries, and safe resume behavior across restarts.
- Persist enough local state to avoid duplicate commits, premature reveals, or lost participation after process restarts.

**2.3.5 — Write operator-facing repo documentation** (~0.5-1 day)
- Explain configuration, wallet setup, artifact verification, and the difference between convenience automation and trust requirements.
- Show how an operator can independently inspect a package instead of treating the sidecar as a black box.

---

### Milestone 2.4: Sidecar Inference Backends

**Duration:** ~1-2 weeks | **Dependencies:** M2.3 | **Status:** Not Started

**Goal:** Support independent scoring through local SGLang and validator-owned Modal/SGLang execution.

Deterministic comparison should work on either Modal or local hardware when the execution setup matches the manifest closely enough: same model snapshot, tokenizer/config, prompt/messages, SGLang image and arguments, deterministic request parameters, parser, selector, and compatible GPU/runtime behavior.

The implementation should be transparent about independence levels:

- Shared foundation endpoint: useful for smoke tests, weak as independent verification.
- Validator-owned Modal/SGLang endpoint: stronger operational independence.
- Validator-owned local GPU/SGLang setup: strongest infrastructure independence.

If a sidecar cannot match the required manifest, it should skip or report the mismatch instead of publishing misleading convergence claims.

**Steps:**

**2.4.1 — Build manifest compatibility checks** (~1 day)
- Compare the local model, runtime, request, parser, and selector setup against the round manifest before inference starts.
- Fail closed on manifest mismatch so sidecars do not publish misleading convergence claims from incompatible runtimes.

**2.4.2 — Support validator-owned Modal/SGLang execution** (~2-3 days)
- Let operators point the sidecar at their own compatible Modal/SGLang endpoint and capture enough runtime detail for comparison.
- Treat validator-owned endpoints as operationally independent from the foundation endpoint, even when the underlying provider is shared.

**2.4.3 — Support local SGLang execution** (~3-5 days)
- Provide a local GPU path for operators who can run the pinned model and runtime themselves.
- Document the practical GPU, driver, memory, and model-download constraints that determine whether local execution is feasible.

**2.4.4 — Normalize inference outputs for comparison** (~1-2 days)
- Store raw response, parsed scores, selector output, and comparison hashes in the same canonical form the foundation expects.
- Use the manifest-declared parser and selector versions so raw-output agreement and parsed-output agreement remain distinguishable.

**2.4.5 — Report mismatch and failure reasons clearly** (~0.5-1 day)
- Distinguish setup mismatch, inference failure, parser failure, and true output divergence.
- Make failure categories structured enough for convergence reports and operator troubleshooting to use the same vocabulary.

---

### Milestone 2.5: Sidecar Chain Integration

**Duration:** ~1 week | **Dependencies:** M2.2, M2.3, M2.4 | **Status:** Not Started

**Goal:** Let sidecars participate in the Phase 2 memo flow without requiring validator node changes.

The sidecar should use existing public PFTL/RPC surfaces and a funded operator wallet to:

- Detect new round announcements.
- Submit commit memos before the commit deadline.
- Submit reveal memos after the commit window opens.
- Handle late rounds, missed rounds, wallet failures, RPC failures, and duplicate submissions safely.

This milestone is about sidecar operations only. No consensus or amendment change is part of Phase 2.

**Steps:**

**2.5.1 — Implement round announcement watching** (~1-2 days)
- Monitor existing PFTL/RPC surfaces for trusted foundation announcements and ignore unrelated memo traffic.
- Track the last processed ledger or transaction marker so restarts do not miss or duplicate round announcements.

**2.5.2 — Submit commit memos idempotently** (~1 day)
- Publish salted commitments once per validator and round, with safe retry behavior for RPC failures.
- Persist transaction hashes and local submission state before moving to the reveal phase.

**2.5.3 — Submit reveal memos after the commit window** (~1 day)
- Reveal the committed output reference and salt only when the protocol window allows it.
- Recompute the local commitment before reveal so the sidecar never reveals data that fails its own commit check.

**2.5.4 — Handle wallet and RPC failure modes** (~1-2 days)
- Detect low balance, failed submission, stale ledgers, duplicate transactions, and missed windows without corrupting local state.
- Prefer a safe skipped round over a duplicate, malformed, or out-of-window memo.

**2.5.5 — Test against devnet-style memo flows** (~1 day)
- Prove that watching, commit submission, reveal submission, and replay protection work before broader devnet testing.
- Use controlled wallets and short test windows so protocol mistakes are visible before community validators participate.

---

### Milestone 2.6: Convergence Monitoring in the Foundation Service

**Duration:** ~1 week | **Dependencies:** M2.2, M2.5 | **Status:** Not Started

**Goal:** Extend the foundation scoring service to validate reveals and publish convergence reports.

The service should aggregate commit and reveal memos, verify salted commitments, fetch validator outputs where needed, and compare each reveal against the foundation result. Reports should distinguish exact raw output matches, parsed score matches, selected UNL matches, override-round matches, and known divergence causes such as runtime or manifest mismatch.

The convergence report becomes a Phase 2 audit artifact published through the same transparent publication channels as other scoring artifacts. The foundation service remains the authoritative VL publisher throughout this phase.

**Steps:**

**2.6.1 — Ingest commit and reveal memos** (~1-2 days)
- Collect Phase 2 participation data from chain history and associate it with the correct scoring round and validator identity.
- Normalize chain data into one round-participation model so reports do not depend on raw RPC response shape.

**2.6.2 — Verify commitments and reveal payloads** (~1 day)
- Recompute commitment hashes, validate salts and output references, and flag invalid or late reveals.
- Distinguish missing, late, malformed, mismatched, and valid reveals in persisted comparison data.

**2.6.3 — Compare validator outputs to foundation outputs** (~1-2 days)
- Separate raw response matches, parsed score matches, selected UNL matches, override matches, and manifest/runtime mismatches.
- Keep comparison levels explicit so one useful match does not hide divergence at another stage.

**2.6.4 — Publish convergence reports** (~1 day)
- Persist and expose a report artifact that explains participation, agreement level, and divergence causes for each round.
- Include enough detail for humans to audit the result while keeping the report stable enough for tooling to consume.

**2.6.5 — Add operational visibility** (~0.5-1 day)
- Surface enough status for operators to understand whether shadow verification is healthy without changing VL authority.
- Keep monitoring read-only with respect to canonical VL publication.

---

### Milestone 2.7: Validator Onboarding and Operations

**Duration:** ~1 week | **Dependencies:** M2.3-M2.6 | **Status:** Not Started

**Goal:** Make shadow verification practical for validator operators.

Documentation and scripts should cover:

- Local SGLang setup.
- Validator-owned Modal/SGLang setup.
- Sidecar configuration.
- Wallet funding and memo submission requirements.
- Normal round participation.
- Missed round recovery.
- Runtime mismatch troubleshooting.
- Upgrade process when the execution manifest changes.

The onboarding path should be short enough for a technically capable validator operator to run without direct foundation assistance.

**Steps:**

**2.7.1 — Write the operator setup guide** (~1 day)
- Cover sidecar installation, configuration, wallet funding, and choosing between Modal/SGLang and local GPU execution.
- Separate local GPU and validator-owned Modal paths so operators can follow the path that matches their infrastructure.

**2.7.2 — Add configuration examples** (~0.5-1 day)
- Provide clear examples for environment variables, network selection, RPC endpoints, and runtime backend selection.
- Include safe defaults and call out values that must be unique per operator or network.

**2.7.3 — Document normal participation and recovery** (~0.5-1 day)
- Explain how to join a round, inspect local state, recover from missed rounds, and restart safely.
- Describe what operators should expect to see before commit, after commit, after reveal, and after convergence reporting.

**2.7.4 — Document troubleshooting and mismatch handling** (~0.5-1 day)
- Help operators distinguish funding, RPC, artifact, runtime, inference, and parser problems.
- Map common symptoms to the logs, state files, or published artifacts that can confirm the cause.

**2.7.5 — Define upgrade expectations** (~0.5 day)
- Explain what operators must do when the execution manifest, model, parser, selector, or sidecar version changes.
- State when an old sidecar should skip a round instead of trying to verify an unsupported manifest.

---

### Milestone 2.8: Devnet Shadow Verification

**Duration:** ~2 weeks | **Dependencies:** M2.0-M2.7 | **Status:** Not Started

**Goal:** Run the full shadow verification lifecycle on devnet with foundation-controlled validators first.

Devnet testing should prove that frozen artifact publication, sidecar monitoring, independent scoring, commit-reveal, and convergence reporting work across repeated rounds. The test should include at least one independent execution environment beyond the foundation scoring service.

Expected validation areas:

- Normal scoring rounds.
- Override rounds.
- Missed commit and missed reveal behavior.
- Runtime mismatch behavior.
- Artifact validation failures.
- Convergence report publication.

**Steps:**

**2.8.1 — Deploy sidecars for foundation-controlled validators** (~1-2 days)
- Start with controlled validator environments so the full lifecycle can be debugged without community operator uncertainty.
- Use known keys, funded sidecar wallets, and observable infrastructure to isolate protocol issues from onboarding issues.

**2.8.2 — Run repeated normal scoring rounds** (~1-2 days)
- Confirm package freeze, sidecar scoring, commit/reveal submission, and convergence reporting across multiple rounds.
- Record per-round timing, participation, output match level, and any manual intervention required.

**2.8.3 — Exercise override and failure scenarios** (~1-2 days)
- Test override rounds, missed commits, missed reveals, runtime mismatch, artifact validation failure, and low participation.
- Confirm each failure mode is reported clearly and does not disrupt canonical VL publication.

**2.8.4 — Compare independent execution environments** (~1-2 days)
- Include at least one validator-side execution path that is not the foundation scoring endpoint.
- Use the comparison to separate transport symmetry from genuine independent execution.

**2.8.5 — Produce a devnet readiness report** (~0.5-1 day)
- Summarize convergence behavior, known issues, and whether the system is ready for testnet shadow rollout.
- Separate rollout blockers from acceptable follow-up work.

---

### Milestone 2.9: Testnet Shadow Rollout

**Duration:** ~1-2 weeks | **Dependencies:** M2.8 | **Status:** Not Started

**Goal:** Roll out shadow verification to testnet without changing VL authority.

The initial testnet rollout should start with foundation-operated validators, then expand to community validators after the operational path is stable. Success is measured by repeated participation, clear convergence reports, understandable divergence reporting, and no disruption to canonical VL publication.

**Steps:**

**2.9.1 — Start with foundation-operated testnet validators** (~1-2 days)
- Run the Phase 2 flow with known operators first while keeping canonical VL publication unchanged.
- Keep the foundation-only fallback path ready while shadow verification is still proving itself.

**2.9.2 — Publish operator instructions and support path** (~0.5-1 day)
- Give community validators a clear setup path, expected behavior, and escalation channel.
- Include expected resource needs, wallet funding expectations, and what participation does and does not affect.

**2.9.3 — Expand participation gradually** (~2-4 days)
- Add community validators as they are ready and monitor whether participation changes convergence or operational stability.
- Prefer opt-in expansion with clear feedback over a deadline that forces operators into unstable setups.

**2.9.4 — Monitor repeated weekly rounds** (~ongoing during rollout)
- Track commits, reveals, match levels, divergence causes, missed windows, and operator support needs.
- Feed repeated issues back into sidecar fixes, operator docs, and convergence-report wording.

**2.9.5 — Decide whether Phase 2 is stable enough for the decision gate** (~0.5 day)
- Confirm that shadow verification provides useful evidence without disrupting foundation VL publication.
- Record the evidence needed for model/judge governance and later authority-transfer planning.

---

### Phase 2 Decision Gate: Ready for Model and Judge Governance

Before model/judge governance and later authority-transfer work begin, Phase 2 must prove:

- Phase 2 artifact bundles and execution manifests are stable across repeated rounds.
- Validator sidecars can score frozen packages without relying on live mutable data.
- Multiple sidecars can commit and reveal outputs across devnet and testnet rounds.
- At least one validator-side execution environment is independent from the foundation scoring endpoint.
- Convergence reports explain exact matches, parsed score matches, selected UNL matches, and divergence causes clearly.
- Foundation VL publication remains reliable while shadow verification runs.
- Validator onboarding is documented well enough for community operators to participate.
- No node-side protocol change is required for Phase 2 shadow verification.

**Additional criteria before Phase 3 technical design:**

- Empirical determinism behavior is measured across local and Modal/SGLang setups.
- The team has enough convergence data to decide whether proof-of-logits, sampled logits, VRF-based sampling, or another proof mechanism is worth pursuing.
- Operational costs and validator hardware requirements are understood well enough to design a sustainable authority-transfer path.

---

## Model Governance Phase: Judge and Scoring Model Selection

**Duration:** ~2-4 weeks | **Difficulty:** ★★★★☆ Hard

**Goal:** Transparently decide whether the current scoring model and judge remain appropriate before validators are asked to rely on an upgraded setup. This phase turns model selection into a public, reproducible governance process rather than a silent foundation-side implementation change.

```
Phase 2 convergence evidence
         |
         v
+-------------------------------+
| Public benchmark/judge repo   |
| Cases + metrics + methodology |
+-------------------------------+
         |
         v
+-------------------------------+
| Deterministic judge execution |
| Pinned SGLang runtime         |
+-------------------------------+
         |
         v
+-------------------------------+
| Candidate model benchmarking  |
| Current model vs alternatives |
+-------------------------------+
         |
         v
+-------------------------------+
| Published selection rationale |
| Keep or upgrade model/judge   |
+-------------------------------+
         |
         v
+-------------------------------+
| Upgrade manifests + sidecar   |
| operator rollout plan         |
+-------------------------------+
         |
         v
Renewed shadow verification before Phase 3A
```

**Important governance boundary:** A model or judge change should not automatically force validator-side trust. Validators need updated manifests, explicit upgrade instructions, and renewed shadow verification before later authority-transfer work depends on the new setup.

---

### Governance Milestone G.1: Public Benchmark and Judge Repository

**Duration:** ~2-3 days | **Dependencies:** Phase 2 shadow-verification design | **Status:** Not Started

**Goal:** Create a public repository that explains how Post Fiat evaluates scoring models and judge behavior.

The repository should contain benchmark cases, expected evaluation criteria, judge prompts/configuration, candidate model configurations, result formats, and enough documentation for external reviewers to understand the selection process. The repo is a transparency and reproducibility artifact; it should not be treated as validator runtime infrastructure.

---

### Governance Milestone G.2: Deterministic Judge Execution

**Duration:** ~3-5 days | **Dependencies:** G.1 | **Status:** Not Started

**Goal:** Make the judge itself reproducible and independently verifiable.

The judge should run through a pinned SGLang inference setup with the same discipline used for validator scoring: fixed model snapshot, tokenizer/config, runtime image/version, request parameters, prompt/messages, parser rules, and canonical output hashing. Judge outputs should be deterministic enough that reviewers can verify the benchmark decision rather than trusting an opaque hosted model response.

---

### Governance Milestone G.3: Candidate Model Benchmarking

**Duration:** ~4-7 days | **Dependencies:** G.1, G.2 | **Status:** Not Started

**Goal:** Compare the current scoring model against candidate replacements using the public benchmark and deterministic judge setup.

The benchmark should evaluate scoring quality, determinism, runtime cost, operational complexity, model availability, SGLang compatibility, and validator-side feasibility. The current model should remain part of the comparison so the outcome can justify either keeping it or replacing it.

---

### Governance Milestone G.4: Published Model and Judge Selection Rationale

**Duration:** ~2-3 days | **Dependencies:** G.3 | **Status:** Not Started

**Goal:** Publish a clear rationale for the selected judge/model setup.

The decision should identify the selected scoring model, selected judge configuration, reasoning/runtime configuration, known limitations, benchmark evidence, and why the chosen setup is acceptable for the next roadmap stage. If the current setup remains best, that should be stated explicitly with evidence.

---

### Governance Milestone G.5: Scoring Service and Sidecar Upgrade Plan

**Duration:** ~2-4 days | **Dependencies:** G.4 | **Status:** Not Started

**Goal:** Plan how an approved model or judge change reaches production systems without a silent validator-side change.

The plan should define versioned execution manifests, scoring-service configuration updates, sidecar compatibility expectations, validator operator upgrade instructions, rollback behavior, and how old/new model rounds are distinguished in artifacts and convergence reports.

---

### Governance Milestone G.6: Renewed Shadow Verification Gate

**Duration:** ~3-5 days | **Dependencies:** G.5 | **Status:** Not Started

**Goal:** Re-run shadow verification after any meaningful model, judge, or runtime change.

Before Phase 3A depends on the selected setup, validators should prove they can reproduce it through Phase 2-style frozen artifacts, deterministic inference, commit-reveal, and convergence reporting. This prevents authority-transfer work from building on an unverified model upgrade.

---

### Model Governance Decision Gate: Ready for Authority Transfer

Before Phase 3A begins, the governance phase must prove:

- The public benchmark/judge repository explains the data, methodology, judge configuration, and candidate model comparison.
- The judge itself runs through a deterministic pinned SGLang setup and produces verifiable outputs.
- The selected scoring model and judge configuration have a published rationale.
- The scoring-service and sidecar upgrade path is documented through versioned manifests and operator instructions.
- Validators are not required to accept silent model or judge changes.
- Renewed shadow verification confirms convergence on the selected setup before authority transfer depends on it.

---

## Phase 3A: Content Authority Transfer

**Duration:** ~2-3 weeks | **Difficulty:** ★★★★☆ Hard

**Goal:** Transfer UNL content authority from the foundation to converged validator results after Phase 2 convergence and the Model Governance decision gate are complete. The foundation still publishes the VL but the content comes from what validators agree on. If convergence drops, the system falls back to foundation-only scoring.

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

**Status:** Research milestone — proceed only if Phase 2 convergence and Model Governance results justify the investment. If Phase 2 achieves >99% output convergence reliably on the selected setup, logit proofs are less critical. If not pursued, the system operates at Phase 2 + Model Governance + 3A level with output-level convergence.

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

**Duration:** ~7-10 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Phase 2 complete, Model Governance decision available, decision to proceed with logit proofs | **Status:** Not started

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

**Duration:** ~7-10 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Milestone 3.1 | **Status:** Not started

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

**Duration:** ~5-7 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** Milestone 3.2 | **Status:** Not started

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

**Duration:** ~5-7 days | **Difficulty:** ★★★★★ Very Hard | **Dependencies:** Phase 2 convergence proven, Model Governance decision gate complete | **Status:** Not started

**Goal:** Transition from "foundation UNL is authoritative" to "converged validator UNL is authoritative." This is a Phase 3A milestone — it does not require proof-of-logits, only proven Phase 2 output convergence on the selected model/judge setup.

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

**Duration:** ~9-13 days | **Difficulty:** ★★★☆☆ Medium | **Dependencies:** None (parallel work — can be built anytime during Phase 1-3, does not gate any other milestone) | **Status:** Not started

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

**Duration:** ~5-7 days | **Difficulty:** ★★★★☆ Hard | **Dependencies:** Milestones 3.4, 3.5 | **Status:** Not started

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
| **Phase 1** | ~4-6 weeks | ★★★★☆ | **Complete.** Foundation scoring live on testnet, VL auto-generated |
| **Phase 2** | ~7-9 weeks | ★★★★★ | Frozen verification artifacts, validator sidecars, commit-reveal, convergence reports |
| **Model Governance** | ~2-4 weeks | ★★★★☆ | Public benchmark/judge repo, deterministic judge execution, selection rationale, upgrade plan |
| **Phase 3A** | ~2-3 weeks | ★★★★☆ | Authority transition, identity verification & scoring integration, system test |
| **Phase 3 Research** | ~5-7 weeks | ★★★★★ | Proof-of-logits (conditional — only if Phase 2 and Model Governance justify it) |
| **Total (through 3A)** | **~16-23 weeks** | | **Converged validator UNL as authoritative source on selected model/judge setup** |

## Summary: Time and Difficulty by Milestone

| Milestone | Duration | Difficulty | Dependencies |
|---|---|---|---|
| **0.1** Model Selection | 2-3 days | ★★★☆☆ | Done |
| **0.2** Modal Setup | 1-2 days | ★★☆☆☆ | Done |
| **0.3** Determinism Research | 2 days | ★★★★☆ | Done — 100% confirmed |
| **0.4** Geolocation Setup & Legal | 1 day | ★☆☆☆☆ | Done |
| **1.1** Scoring Service Repo Setup | 1-2 days | ★★☆☆☆ | Phase 0 — Done |
| **1.2** Infrastructure Provisioning | 1 day | ★★☆☆☆ | 1.1 — Done |
| **1.3** postfiatd Version Update | 3-4 days | ★★★☆☆ | 1.2 — Done |
| **1.4** Data Collection Pipeline | 3-4 days | ★★★☆☆ | 1.1, 1.3 — Done |
| **1.5** LLM Scoring Integration | 4-5 days | ★★★☆☆ | 1.1, 1.4 — Done |
| **1.6** VL Generation | 3-4 days | ★★★☆☆ | 1.5 — Done |
| **1.7** IPFS Audit Trail | 2-3 days | ★★☆☆☆ | 1.4, 1.5 — Done |
| **1.8** On-Chain Memo | 1-2 days | ★★☆☆☆ | 1.6, 1.7 — Done |
| **1.9** Orchestrator & Scheduler | 3-4 days | ★★★☆☆ | 1.4-1.8 — Done |
| **1.10** Devnet Testing & Validation | 13-19 days | ★★★☆☆ | 1.2, 1.9 — Done |
| **1.11** Admin Override Endpoints | 3-5 days | ★★★☆☆ | 1.10.6, 1.10.7 — Done |
| **1.12** Explorer Scoring Pages | 9-14 days | ★★★☆☆ | 1.10.5 — Done |
| **1.13** Testnet Deployment | 3-5 weeks elapsed (~4-6 days active) | ★★★☆☆ | 1.10, 1.11 — Done |
| **2.0** Verification Artifact Bundle and Execution Manifest | ~1 week | ★★★★☆ | Phase 1 |
| **2.1** Frozen Input Package Lifecycle | ~1 week | ★★★☆☆ | 2.0 |
| **2.2** Commit-Reveal Protocol | ~1 week | ★★★★☆ | 2.0, 2.1 |
| **2.3** Validator Sidecar Repository | ~1 week | ★★★☆☆ | 2.0, 2.1, 2.2 |
| **2.4** Sidecar Inference Backends | ~1-2 weeks | ★★★★★ | 2.3 |
| **2.5** Sidecar Chain Integration | ~1 week | ★★★★☆ | 2.2, 2.3, 2.4 |
| **2.6** Convergence Monitoring in the Foundation Service | ~1 week | ★★★★☆ | 2.2, 2.5 |
| **2.7** Validator Onboarding and Operations | ~1 week | ★★☆☆☆ | 2.3-2.6 |
| **2.8** Devnet Shadow Verification | ~2 weeks | ★★★★☆ | 2.0-2.7 |
| **2.9** Testnet Shadow Rollout | ~1-2 weeks | ★★★★☆ | 2.8 |
| **G.1** Public Benchmark and Judge Repository | 2-3 days | ★★★☆☆ | Phase 2 shadow-verification design |
| **G.2** Deterministic Judge Execution | 3-5 days | ★★★★☆ | G.1 |
| **G.3** Candidate Model Benchmarking | 4-7 days | ★★★★☆ | G.1, G.2 |
| **G.4** Model and Judge Selection Rationale | 2-3 days | ★★★☆☆ | G.3 |
| **G.5** Scoring Service and Sidecar Upgrade Plan | 2-4 days | ★★★☆☆ | G.4 |
| **G.6** Renewed Shadow Verification Gate | 3-5 days | ★★★★☆ | G.5 |
| **3.4** Authority Transfer | 5-7 days | ★★★★★ | Phase 2 convergence proven, Model Governance complete |
| **3.5** Identity Verification & Scoring Integration | 9-13 days | ★★★☆☆ | None (parallel) |
| **3.6** Full System Test | 5-7 days | ★★★★☆ | 3.4, 3.5 |
| **3.1** Logit Commitments | 7-10 days | ★★★★★ | Phase 2 and Model Governance (research, conditional) |
| **3.2** Spot-Check Tooling | 7-10 days | ★★★★★ | 3.1 (research, conditional) |
| **3.3** Verification Publish | 5-7 days | ★★★☆☆ | 3.2 (research, conditional) |
