# Deploy Qwen3-235B-A22B on RunPod (Milestone 0.2)

This guide walks through deploying `Qwen3-235B-A22B` on RunPod serverless infrastructure. It assumes zero prior RunPod experience.

---

## Context

Milestone 0.1 selected `qwen3-235b-thinking` as the primary model for the Dynamic UNL scoring pipeline. The Thinking-2507 dedicated fine-tune was also evaluated and rejected — it was 10x slower, 3x less stable, and produced worse score calibration on the validator scoring task (see `docs/WhyNotThinking2507.md`).

The HuggingFace model is [`Qwen/Qwen3-235B-A22B`](https://huggingface.co/Qwen/Qwen3-235B-A22B). This is a Mixture-of-Experts model: 235B total parameters, 22B active per forward pass. It natively supports thinking mode (enabled by default) — the same mode the benchmark used via OpenRouter's `reasoning.effort = "high"` parameter. On self-hosted SGLang, thinking mode is active by default with no extra configuration.

At GPTQ-Int4 quantization the model requires ~125GB VRAM, fitting on a single H200 (141GB) with ~16GB headroom for KV cache.

This milestone (0.2) deploys the model on RunPod to confirm it runs correctly on target hardware: single NVIDIA H200 GPU, SGLang backend, temperature 0.

---

## Part 1: Create a RunPod Account

### 1.1 — Sign Up

1. Go to [runpod.io](https://www.runpod.io)
2. Click **Sign Up** (top-right)
3. Create an account with email or GitHub/Google SSO
4. Verify your email if prompted

### 1.2 — Add a Payment Method

1. After logging in, click your profile icon (top-right) → **Settings**
2. Go to the **Billing** tab
3. Click **Add Payment Method**
4. Add a credit card or link PayPal
5. Add credits to your account — RunPod requires a minimum balance for H200 endpoints. Select **$200**, enable **Auto-pay** (threshold: $100, auto-add: $200) so the account never runs dry during development, and click **"Go to Checkout"**. You only pay for active GPU seconds — idle workers cost nothing

### 1.3 — Generate an API Key

1. Go to **Settings** → **API Keys**
2. Click **Create API Key**
3. Give it a name like `dynamic-unl-scoring`
4. Copy the key immediately — you will not see it again
5. Save it somewhere secure (password manager, not a text file)

---

## Part 2: Deploy a Serverless Endpoint

RunPod "Serverless" means your GPU worker spins up on demand and shuts down when idle. You pay nothing when no requests are in flight.

### 2.1 — Navigate to Serverless

1. In the RunPod dashboard, click **Serverless** in the left sidebar
2. Click **+ New Endpoint**

### 2.2 — Select the SGLang Template

1. You will see a list of pre-built templates. Search for **SGLang**
2. Click on the **SGLang** template card to open its info page
3. You will see a page with the SGLang logo, a description, an environment variables reference table, and API usage docs. This page is **just documentation** — you cannot edit anything here yet
4. Click the yellow **"Deploy 1.2.0"** button (top-right corner). This opens the actual configuration dialog

### 2.3 — Configure the Model

After clicking "Deploy 1.2.0", a **"Configure SGLang"** dialog opens.

**Set only the Model field:**

```
Qwen/Qwen3-235B-A22B-GPTQ-Int4
```

**Do NOT change any other fields** — leave Quantization, Trust Remote Code, Context Length, Data Type, and everything else at their defaults. SGLang auto-detects the model's quantization method and settings from the model's config files on HuggingFace.

Click **Next** at the bottom-right.

### 2.4 — Choose Deployment Type

A **"Deploy SGLang"** dialog appears with two options: **Endpoint** and **Pod**.

- **Endpoint** should already be selected (highlighted) — this is the serverless option with autoscaling and scale-to-zero. This is what we want.
- Do NOT select "Pod" — that's a persistent GPU instance that charges 24/7.

Click **"Create Endpoint"** (purple button, bottom-right).

### 2.5 — Edit Endpoint Configuration (Critical)

After creating the endpoint, you land on the endpoint overview page. **The endpoint defaults to a small GPU (e.g., "24 GB Pro") which is far too small.** You must immediately edit the endpoint to fix the GPU type and other settings.

1. On the endpoint overview page, click the **"Manage"** dropdown (top-right) → **"Edit Endpoint"**

The Edit Endpoint panel has four sections. Configure them as follows:

#### GPU Configuration (top of the panel)

The panel shows a list of GPU tiers with checkboxes, supply indicators, and per-second pricing. **Check only the 141 GB option** (this is the H200 SXM). Uncheck everything else. Use the arrow buttons to make it **1st** priority.

Do NOT select any smaller GPU — the model is ~125GB and will not load on anything under 141GB.

#### Workers & Timeout (middle of the panel)

| Setting | Value | Why |
|---------|-------|-----|
| **Endpoint name** | `qwen3-235b-thinking` | Descriptive name (default is "SGLang 1.2.0") |
| **Max workers** | `1` | Scoring is sequential — one request at a time |
| **Active workers** | `0` | Scale to zero when idle (no cost when not scoring) |
| **GPU count** | `1` | Single GPU required for deterministic logits |
| **Idle timeout** | `300 sec` | Default is 5 sec which is far too low — the worker would shut down after every request, causing a long cold start each time. Set to 300 (5 minutes) so the worker stays warm between requests |
| **Execution timeout** | `600 sec` | Maximum time a single request can run. 600 sec (10 min) is sufficient |
| **FlashBoot** | `enabled` | Reduces cold starts. Leave checked |

#### Docker Configuration & Advanced (bottom of the panel)

| Setting | Value |
|---------|-------|
| **Container disk** | `100 GB` |
| **Enabled GPU types** | `H200 SXM` checked |

Everything else stays at defaults.

#### Save

Click **"Save Endpoint"** (purple button, bottom-right). The endpoint will reinitialize with the correct GPU. If H200 supply is low, it will queue until one becomes available.

**Note on thinking mode:** This model has thinking enabled by default. No extra configuration needed — the model will produce a thinking trace followed by the answer, just like the OpenRouter benchmarks.

### 2.6 — Quantized Model Variants (Reference)

| Variant | Repo | Size | Fits H200? | Source |
|---------|------|------|-----------|--------|
| **GPTQ-Int4** — recommended | [`Qwen/Qwen3-235B-A22B-GPTQ-Int4`](https://huggingface.co/Qwen/Qwen3-235B-A22B-GPTQ-Int4) | ~125GB | Yes | Official (Qwen) |
| AWQ (4-bit) — fallback | [`QuixiAI/Qwen3-235B-A22B-AWQ`](https://huggingface.co/QuixiAI/Qwen3-235B-A22B-AWQ) | ~118GB | Yes | Community |
| FP8 | [`Qwen/Qwen3-235B-A22B-FP8`](https://huggingface.co/Qwen/Qwen3-235B-A22B-FP8) | ~235GB | No | Official (Qwen) |
| BF16 (full precision) | [`Qwen/Qwen3-235B-A22B`](https://huggingface.co/Qwen/Qwen3-235B-A22B) | ~470GB | No | Official (Qwen) |

Use the **official GPTQ-Int4** variant. It is from Qwen directly, fits on a single H200, and Qwen explicitly recommends SGLang for deployment with GPTQ models. The community AWQ variant is a fallback if GPTQ causes issues.

### 2.7 — Wait for Deployment

1. After saving, the endpoint will begin initializing
2. The endpoint will show status **Initializing** → **Ready**
3. H200 GPUs are high-demand — if the dashboard shows "Supply of your primary GPU choice is currently low", the endpoint is waiting for a GPU to become available. This is normal and can take anywhere from minutes to hours
4. The first deploy takes longer because model weights need to download. This can take 10-30 minutes after a GPU is allocated
5. Note your **Endpoint ID** — it appears in the endpoint URL and on the dashboard

---

## Part 3: Test the Endpoint

### 3.1 — Prepare Your Environment

On your local machine, set up the environment variables:

```bash
export RUNPOD_API_KEY="your_api_key_from_step_1.3"
export RUNPOD_ENDPOINT_ID="your_endpoint_id_from_step_2.7"
```

### 3.2 — Quick Smoke Test (Simple Prompt)

Send a minimal request to verify the endpoint responds:

```bash
curl -s -X POST "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/runsync" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {"role": "user", "content": "What is 2+2? Reply with just the number."}
      ],
      "max_tokens": 256,
      "temperature": 0
    }
  }' | python3 -m json.tool
```

**What you should see:**
- A JSON response with `"status": "COMPLETED"`
- An `"output"` object containing the answer
- The response may include a thinking trace before the answer — this is expected
- If you see `"status": "IN_QUEUE"`, the worker is cold-starting — wait 2-5 minutes and try again
- If you see `"status": "FAILED"`, check the error message and the troubleshooting table in 3.6

The endpoint also supports an **OpenAI-compatible API** at `https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/openai/v1` — this is what the Phase 1 scoring service will use via the `openai` Python SDK.

### 3.3 — Check Cold Start Time

1. Wait for the worker to scale down (after 5 minutes of no requests, the worker count should show 0)
2. Send the smoke test request again
3. Note the total time from request to response — this is your cold start time
4. Typical cold start for a 235B model: **3-10 minutes** (loading weights into GPU memory)
5. Subsequent requests while the worker is warm should complete in ~2 minutes for the full scoring prompt

**Note:** The `runsync` endpoint has a default timeout (typically 60-90 seconds). For cold starts that exceed this, use the async endpoint:

```bash
# Submit async request (returns immediately with a job ID)
JOB_RESPONSE=$(curl -s -X POST "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/run" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {"role": "user", "content": "Say hello in one word."}
      ],
      "max_tokens": 64,
      "temperature": 0
    }
  }')

echo "$JOB_RESPONSE" | python3 -m json.tool

# Extract the job ID
JOB_ID=$(echo "$JOB_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Poll for completion (check every 30 seconds)
curl -s "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/status/${JOB_ID}" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" | python3 -m json.tool
```

Keep polling until `"status"` changes from `"IN_QUEUE"` or `"IN_PROGRESS"` to `"COMPLETED"` or `"FAILED"`.

### 3.4 — Full Scoring Prompt Test

Run the test script from the repo:

```bash
cd /Users/dravlic/Desktop/CompanyProjects/PostFiat/repositories/dynamic-unl-scoring
python3 benchmarks/test_runpod.py
```

This sends the full 42-validator scoring prompt to the RunPod endpoint and saves the result to `results/runpod/run_<timestamp>.json`.

Make sure your `.env` file has `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` set before running.

### 3.5 — What Success Looks Like

| Check | Expected Result |
|-------|----------------|
| Endpoint deploys without error | Status shows "Ready" on RunPod dashboard |
| Smoke test returns a response | `"status": "COMPLETED"` with coherent text |
| Cold start completes | Worker loads model and responds (even if it takes 5-10 min) |
| Full scoring prompt returns valid JSON | 42 validator entries with `v001`-`v042` keys |
| Each entry has `score` (0-100) and `reasoning` | Scores are integers, reasoning is non-empty |
| Score distribution is meaningful | Range spans at least 30 points (not all clustered at 85-90) |
| Scores align with data quality | Validators with near-perfect agreement score higher than those with poor agreement |

**Expected performance** (based on OpenRouter benchmarks with this model):
- ~6,500 completion tokens per run
- ~2 minutes per scoring run on a warm worker
- Score range typically 0-96 with a mean around 80
- 8/8 complete runs in the benchmark — high reliability

### 3.6 — Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Endpoint stuck in "Initializing" | H200 GPU supply is low | Wait. All data centers should be enabled. Do not attach Network Volumes. |
| `"status": "FAILED"` with OOM error | Model too large for GPU | Confirm you selected 141 GB GPU (H200), not a smaller one |
| Response is empty or garbled | Wrong input format | Check the template docs for the expected request format |
| JSON output is malformed | Model did not follow instructions | Retry. If persistent, check that `temperature` is set to `0` |
| Timeout on `runsync` | Cold start exceeds sync timeout | Use the async `run` + `status` flow instead (see Step 3.3) |
| `401 Unauthorized` | Wrong API key | Regenerate the key in Settings → API Keys |
| `404 Not Found` | Wrong endpoint ID | Check the endpoint ID on the dashboard |

---

## Part 4: Record Your Configuration

After a successful test, record these values for Phase 1 development.

Create or update the `.env` file in the repo root:

```bash
cd /Users/dravlic/Desktop/CompanyProjects/PostFiat/repositories/dynamic-unl-scoring

cat >> .env << 'EOF'
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_endpoint_id
EOF
```

Configuration reference:

```
Endpoint Name:       qwen3-235b-thinking
Endpoint ID:         <from dashboard>
Model:               Qwen/Qwen3-235B-A22B-GPTQ-Int4
Quantization:        GPTQ-Int4 (official Qwen)
GPU Type:            H200 SXM 141GB
Template:            SGLang 1.2.0
Max Workers:         1
Active Workers:      0
Idle Timeout:        300s
Execution Timeout:   600s
Container Disk:      100GB
Cold Start Time:     <measured in Step 3.3>
Scoring Latency:     <measured in Step 3.4, warm worker>
```

---

## Part 5: Update .env.example

The `.env.example` has already been updated with RunPod variables:

```
OPENROUTER_API_KEY=your_key_here
RUNPOD_API_KEY=your_runpod_api_key_here
RUNPOD_ENDPOINT_ID=your_endpoint_id_here
```

---

## Part 6: Cost Reference

| Activity | Estimated Cost |
|----------|---------------|
| H200 GPU active time | ~$3.49/hr (RunPod on-demand pricing, varies) |
| One full scoring run (warm worker) | ~$0.05-0.15 (~2 min of GPU time) |
| Cold start overhead | ~$0.30-0.60 (model loading adds 5-10 min of GPU time) |
| Idle between requests | $0.00 (scale-to-zero) |
| Monthly estimate (weekly scoring) | ~$5-15 |

---

## Part 7: Clean Up After Testing

After validating the deployment, let the worker scale to zero naturally (after 5 minutes of no requests). The endpoint costs nothing when idle.

To stop all charges entirely:

1. Go to **Serverless** → click your endpoint
2. Click **Delete Endpoint**
3. This removes the endpoint. You would need to redeploy from scratch later.

For Milestone 0.2, leave the endpoint running with scale-to-zero.

---

## Summary Checklist

- [ ] RunPod account created with payment method
- [ ] API key generated and saved securely
- [ ] Serverless endpoint deployed with SGLang template + H200 GPU
- [ ] Model configured: `Qwen/Qwen3-235B-A22B-GPTQ-Int4` (do NOT manually set Quantization or Trust Remote Code — let SGLang auto-detect)
- [ ] Smoke test passed (simple prompt returns coherent response)
- [ ] Cold start time measured and documented
- [ ] Full scoring prompt test passed (42 validators, valid JSON, meaningful scores)
- [ ] Endpoint ID and API key stored in `.env`
- [ ] Configuration details recorded for Phase 1 development
