# Model Selection Benchmark (Milestone 0.1)

The first concrete step in the Dynamic UNL pipeline: select an open-weight LLM for validator scoring. This document covers the hardware constraints, model elimination process, benchmark methodology, and the rationale behind every decision.

---

## Why Model Selection Comes First

The Dynamic UNL system uses an AI model to score validators for UNL inclusion. Before building the scoring pipeline, data collection, IPFS publication, or any of the Phase 1–3 infrastructure, we need to know which model we're building around. The model choice affects:

- GPU hardware requirements (which determines validator costs)
- Inference engine configuration (SGLang deterministic settings)
- Prompt engineering approach (thinking vs direct output)
- Expected output quality and format compliance

Everything downstream depends on this decision.

---

## The Hard Constraint: Single H200

Design.md requires **one mandatory GPU type** for all validators. This is non-negotiable — proof-of-logits (Phase 3) requires identical logit output across all validators, which means same GPU + same driver + same model.

**Why single GPU, not multi-GPU:** Tensor parallelism across multiple GPUs introduces non-determinism in floating-point operations due to different reduction orderings. A model that requires 2x GPUs cannot guarantee identical logits across validators, which breaks Layer 2 verification.

**The chosen GPU: NVIDIA H200 (141GB VRAM).** This is the highest single-GPU VRAM available on cloud GPU platforms (RunPod) at a reasonable cost. The model must fit entirely on one H200 at 4-bit quantization with enough headroom for KV cache during inference.

### Why Not B200?

The B200 offers 192GB VRAM (51GB more than H200). This was considered and rejected:

- The extra 51GB would theoretically allow GLM 4.6/4.7 (355B params, ~178GB at 4-bit) to load
- But with only ~14GB remaining after weights, there isn't enough headroom for KV cache
- Our scoring prompt sends all ~42 validator profiles in a single context (10-15K input tokens + up to 4K output tokens), and KV cache for a 355B model at those sequence lengths exceeds the remaining VRAM
- The B200 doesn't meaningfully expand our model choices beyond what the H200 already supports
- B200 availability on cloud GPU platforms is also more limited and more expensive

---

## Model Elimination: LiveBench Reasoning Rankings

We used [LiveBench](https://livebench.ai) open-weight reasoning scores to identify candidates. The approach was straightforward: check reasoning scores, identify models that fit on a single H200, and shortlist the best ones for hands-on testing.

### Full Rankings (Top 10 Open-Weight by Reasoning Average)

| Rank | Model | Reasoning Avg | Total Params | 4-bit VRAM | Fits H200? |
|------|-------|--------------|-------------|------------|-----------|
| 1 | DeepSeek V3.2 Thinking | 77.17 | 685B | ~343GB | No |
| 2 | Kimi K2.5 Thinking | 75.96 | 1,000B | ~500GB | No |
| 3 | GLM 5 | 69.11 | 745B | ~373GB | No |
| 4 | DeepSeek V3.2 Exp Thinking | 64.37 | 685B | ~343GB | No |
| 5 | Kimi K2 Thinking | 63.49 | ~1,000B | ~500GB | No |
| 6 | GLM 4.6 | 62.06 | ~355B | ~178GB | No |
| 7 | GLM 4.7 | 59.73 | 355B | ~178GB | No |
| **8** | **Qwen3-235B-A22B Thinking** | **59.40** | **235B** | **~118GB** | **Yes** |
| **9** | **MiniMax M2.5** | **59.30** | **230B** | **~115GB** | **Yes** |
| 10 | Qwen3-235B-A22B Instruct | 58.43 | 235B | ~118GB | Yes |

**The top 7 models are all eliminated by the single-H200 constraint.** Every model above rank 8 requires 178GB+ at 4-bit quantization, exceeding the H200's 141GB. The constraint is clear and binary — there's no room for negotiation on GPU determinism requirements.

### What Survived: Two Model Families

Only two model families fit on a single H200 at 4-bit quantization:

1. **Qwen3-235B-A22B** (Alibaba) — 235B total params, 22B active per forward pass (MoE architecture), ~118GB at 4-bit. Leaves ~23GB for KV cache and activations.
2. **MiniMax M2.5** (MiniMax) — 230B total params, 10B active (MoE), ~115GB at 4-bit. Leaves ~26GB for KV cache and activations.

Both have comfortable headroom for our scoring prompt's KV cache requirements.

---

## Selected Models for Benchmarking

We benchmark 3 variants — two modes of Qwen3-235B and one MiniMax M2.5:

| # | Model | Reasoning Score | IF Score | Rationale |
|---|-------|----------------|----------|-----------|
| 1 | **Qwen3-235B-A22B (Thinking)** | 59.40 | 40.64 | Highest reasoning among H200-compatible models. "Thinking" mode produces chain-of-thought which may improve scoring quality. Alex's top pick. |
| 2 | **Qwen3-235B-A22B (Instruct)** | 58.43 | 21.72 | Same weights, non-thinking mode. May produce more predictable JSON output. Tests whether thinking trace helps or hurts for this task. |
| 3 | **MiniMax M2.5** | 59.30 | 57.23 | Virtually tied on reasoning but significantly better Instruction Following (57.23 vs 40.64). IF matters for reliable JSON output. |

### Why These 3 Specifically

**Reasoning scores are essentially tied (~58-59).** LiveBench can't meaningfully differentiate them at this margin. The benchmark on our actual scoring task is the tiebreaker.

**Instruction Following is the interesting variable.** MiniMax M2.5 scores 57.23 on IF vs Qwen3 Thinking at 40.64 — a large gap. For a production scoring pipeline that must output valid JSON with a specific schema every time, IF reliability is critical. If MiniMax produces valid structured output more consistently, that's a real advantage.

**Testing both Qwen3 modes tells us something specific:** Does the thinking trace (chain-of-thought reasoning before the JSON output) improve scoring quality enough to offset potential format compliance issues? If the Instruct (non-thinking) variant produces equally good scores with better JSON compliance, thinking mode adds cost and complexity for no benefit.

### Naming Clarifications

- "Qwen 3.5" (as mentioned in early discussions) → the actual model is **Qwen3-235B-A22B** (Qwen3 family, released July 2025, MoE architecture)
- "MiniMax 2.5" → **MiniMax M2.5** (230B total, 10B active), the successor to the older M1-80k
- In this repo's benchmark script, the label **`qwen3-235b-thinking`** specifically means OpenRouter model **`qwen/qwen3-235b-a22b`** with thinking enabled via `reasoning.effort = "high"`. It does **not** automatically mean the later dedicated checkpoint **`Qwen/Qwen3-235B-A22B-Thinking-2507`**.

---

## Benchmark Methodology

### Data: Real Validator Snapshot from VHS Testnet

We test against real production data, not synthetic examples. The `fetch_vhs_data.py` script pulls a live snapshot from the VHS (Validator History Service) testnet API:

**Endpoints:**
- `GET https://vhs.testnet.postfiat.org/v1/network/validators` — Returns all 42 validators with agreement scores (1h, 24h, 30-day windows), domain, server version, fee votes, UNL status
- `GET https://vhs.testnet.postfiat.org/v1/network/topology/nodes` — Returns all 44 network nodes with IP, geographic location, peer counts, uptime, latency

**Data joining:** VHS tracks validators and topology nodes as separate entities with different key types (validator signing/master keys vs node peer-to-peer identity keys). These cannot be joined directly through the API. The snapshot includes both datasets:
- **Validators** are the primary scoring input (agreement, version, domain, fees)
- **Network topology** provides geographic context (country distribution across all nodes)

In the full Phase 1 pipeline, per-validator geolocation will come from MaxMind GeoIP lookups on validator IPs collected by the foundation. For this benchmark, the models score based on available performance data and can reference the network's overall geographic distribution.

**Snapshot characteristics (as of March 2026 fetch):**
- 42 validators, 44 topology nodes
- 30-day agreement scores range from 0.00145 to 1.00000 (excellent differentiation)
- 20 validators have domains, 22 do not
- 16 unique domains across domain-verified validators
- All validators running server version 3.0.0
- Network spans 8 countries: US (24 nodes), Germany (8), Finland (4), UK (3), France (2), Bulgaria (1), Sweden (1), Canada (1)

This dataset has enough variety to meaningfully test score differentiation — models must handle validators ranging from near-perfect (1.0 agreement) to severely degraded (0.001 agreement).

### Scoring Prompt Design

The scoring prompt (`prompts/scoring_v1.txt`) is derived directly from Design.md's scoring criteria. It has two parts:

**System prompt** defines the scoring rubric with 6 dimensions in order of importance:

1. **Consensus Performance** (highest weight) — Agreement score is the primary signal. >99.9% is expected, <99% is a serious issue.
2. **Operational Reliability** (high weight) — Uptime consistency, domain verification.
3. **Software Diligence** (moderate weight) — Running current server version, reasonable fee votes.
4. **Geographic/Infrastructure Diversity** (moderate weight) — Country concentration, ASN/ISP concentration, operator concentration. Scored relative to the full validator set.
5. **Identity and Reputation** (low-moderate weight) — Verified domain and organizational identity. Missing identity data (common on testnet) is treated as neutral, not penalized.
6. **Observer-Dependent Metrics** (low weight) — Latency and peer count measured from VHS's single vantage point. Explicitly deprioritized per Design.md since they don't represent universal truth.

**Scoring rules** prevent common LLM failure modes:
- Diversity adjustments reward underrepresented attributes rather than punishing common ones
- Perfect-performing validators score 85+ regardless of location
- Scores below 30 reserved for validators with serious issues
- Full range usage required — no clustering all scores in 80-90

**User prompt** injects the validator data and topology data as JSON, but each validator is represented by a short stable `validator_id` (`v001`, `v002`, ...). The model returns a JSON object keyed by those IDs, each with a `score` (integer 0-100) and `reasoning` (string). The benchmark script remaps IDs back to validator master public keys after parsing so we avoid key-copy errors in model output.

### Why OpenRouter

[OpenRouter](https://openrouter.ai) provides an OpenAI-compatible API with access to all 3 candidate models. Benefits for benchmarking:

- **Pay-per-token, no infrastructure setup.** We're testing model quality, not deployment. No need to spin up GPU instances just to evaluate output.
- **All 3 models available on one platform.** Same API interface, same token counting, fair comparison.
- **OpenAI SDK compatible.** The `openai` Python package works directly — no custom API clients.

For production (Phase 1+), the model runs locally on the validator's GPU sidecar via SGLang. OpenRouter is purely a benchmarking convenience.

### Benchmark Execution

The `benchmark_models.py` script runs each model 5 times with identical input:

**Per run:**
1. Load the scoring prompt template and testnet snapshot
2. Construct messages (system prompt + user prompt with injected data)
3. Call OpenRouter API with `temperature=0`, JSON output mode
4. For Qwen3 Thinking: `reasoning.effort = "high"` (enables chain-of-thought)
5. For Qwen3 Instruct: `reasoning.effort = "none"` (direct output)
6. Parse the response, validate the returned validator IDs, remap them back to master public keys, and compute score statistics
7. Save the full result (raw response, parsed scores, timing, token usage) to `results/<session_name>/<model_name>/run_<N>.json`

**Why 5 runs:** Even at temperature 0, model outputs can vary slightly due to infrastructure-level non-determinism (different backend instances, batching, etc.). Five runs reveals consistency — if a model's scores for the same validator fluctuate by more than ±3 points across runs, that's a reliability concern for production use where determinism matters.

**Why temperature 0:** Design.md specifies temperature 0 with greedy decoding for production scoring. We benchmark under the same conditions we'll deploy under.

---

## Evaluation Criteria

After the benchmark runs, results are compared on these dimensions:

### 1. JSON Compliance
Does the model output valid JSON in the expected schema every time? A model that occasionally outputs malformed JSON, omits validators, or wraps output in markdown code blocks is problematic for a production pipeline that must run unattended.

### 2. Score Differentiation
Are scores spread meaningfully across the 0-100 range? The testnet data has validators ranging from 0.001 to 1.0 agreement — a good model should produce a wide score distribution. If all 42 validators score between 85-90, the model isn't using the data effectively.

### 3. Reasoning Quality
Does the reasoning string reference actual metrics from the validator data? Good reasoning cites specific agreement scores, version numbers, domain status. Bad reasoning is generic ("this validator performs well") or hallucinates data not present in the input.

### 4. Diversity Awareness
Does the model factor in geographic and infrastructure concentration when applicable? Given the topology data showing 24/44 nodes in the US, a model that ignores concentration entirely is missing a key scoring dimension.

### 5. Consistency Across Runs
Do scores for the same validator stay stable across 5 runs (within ±3 points)? Production scoring requires predictability — if the same input produces wildly different scores, the model can't be trusted for UNL decisions.

### Tiebreaker Policy

If Qwen3-235B and MiniMax M2.5 are close on all criteria, prefer Qwen3-235B. Rationale:
- Alex's top pick based on ecosystem familiarity
- Larger community and tooling ecosystem (Alibaba/Qwen)
- Both fit comfortably on H200 but Qwen3 has more deployment documentation for SGLang

---

## Repository Structure

```
dynamic-unl-scoring/
├── scripts/
│   ├── fetch_vhs_data.py       # Pull validator data from VHS testnet API
│   └── benchmark_models.py     # Run scoring prompt against each model via OpenRouter
├── prompts/
│   └── scoring_v1.txt          # Scoring prompt template (system + user)
├── data/
│   ├── .gitkeep
│   └── testnet_snapshot.json   # Fetched VHS snapshot (committed for reproducibility)
├── results/                    # Model outputs (gitignored except .gitkeep)
│   └── .gitkeep
├── docs/
│   └── ModelSelectionBenchmark.md  # This document
├── requirements.txt            # httpx, openai, python-dotenv
├── .gitignore
├── .env.example                # OPENROUTER_API_KEY=your_key_here
└── README.md
```

**Why this repo exists separately from postfiatd:** The scoring pipeline is a separate service that runs alongside the validator, not inside the consensus daemon. Starting it here during Phase 0 means benchmarking code naturally evolves into the Phase 1 scoring service without a migration. This follows ImplementationPlan Milestone 1.1.

---

## What Comes Next

1. **Run the benchmark** — Execute `benchmark_models.py` with an OpenRouter API key. 15 total API calls (3 models × 5 runs).
2. **Analyze results** — Compare models side-by-side on the evaluation criteria above. Document the winner and why.
3. **Milestone 0.2: RunPod confirmation** — Deploy the winning model on RunPod serverless to confirm it runs correctly in the target environment (single H200, SGLang, deterministic mode).
4. **Phase 1 build** — The scoring pipeline, IPFS publication, and on-chain UNL hash publication. The model choice is locked; everything else builds around it.
