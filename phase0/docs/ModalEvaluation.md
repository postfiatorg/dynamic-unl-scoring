# Modal Platform Evaluation for SGLang Serverless Deployment

Evaluation of [Modal](https://modal.com) as a deployment platform for the Dynamic UNL scoring pipeline, following the decision to move away from RunPod serverless (see `WhyNotRunPodServerless.md`).

---

## 1. Platform Overview

Modal is a serverless compute platform where infrastructure is defined in Python code rather than configured through a web UI. A deployment is a Python script that specifies the container image, GPU type, volumes, and server lifecycle — then deployed with `modal deploy`.

Key characteristics:

- **Per-second billing** — charges only for actual compute time, no idle costs at scale-to-zero
- **Python-native** — no Docker builds, no YAML, no UI configuration. Everything is version-controlled code
- **GPU support** — H200, H100, A100, L4, B200 and others available as a single parameter (`gpu="H200"`)
- **Volumes** — persistent storage for model weights, loaded at 1-2 GB/s on container startup
- **Autoscaling** — containers scale up on demand and down to zero when idle

### Plans and Credits

| Plan | Base Cost | Free Credits | Container Limit | GPU Concurrency |
|---|---|---|---|---|
| Starter | $0/month | $30/month | 100 | 10 |
| Team | $250/month | $100/month | 1,000 | 50 |

The Starter plan is sufficient for Phase 0 evaluation and early Phase 1 development.

---

## 2. H200 GPU Availability

H200 is listed as a standard GPU option on Modal with no special restrictions, approval processes, or waitlists mentioned. Pricing: **$0.001261/sec (~$4.54/hr)**.

Unlike RunPod, Modal does not require region-specific network volumes to match GPU availability. Volumes are accessible from any region where the GPU is available.

| GPU | Price/hr | VRAM | Notes |
|---|---|---|---|
| H200 | $4.54 | 141 GB | Target for Qwen3-235B GPTQ-Int4 (~125GB) |
| H100 | $3.95 | 80 GB | Too small for our model |
| B200 | $6.25 | 180 GB | Overkill but available as fallback |

**Starter plan limits:** 10 concurrent GPU containers. This is more than sufficient — the scoring pipeline uses a single container.

---

## 3. SGLang Integration

Modal maintains official SGLang examples and uses **SGLang v0.5.6** (newer than the v0.5.2 used in the RunPod custom image). The integration is well-documented with multiple example deployments.

### Official Modal SGLang Examples

| Example | Model | GPU | Relevance |
|---|---|---|---|
| [Qwen 3-8B with Snapshots](https://modal.com/docs/examples/sglang_snapshot) | Qwen 3-8B FP8 | H100 | SGLang setup pattern, volume caching, snapshot optimization |
| [Low-Latency Qwen 3-8B](https://modal.com/docs/examples/sglang_low_latency) | Qwen 3-8B FP8 | 2x H100 | Speculative decoding, advanced configuration |
| [Very Large Models](https://modal.com/docs/examples/very_large_models) | GLM 4.7, DeepSeek V3 | 4x H200 | Large model weight caching, H200 deployment |

### Deterministic Inference

The `--enable-deterministic-inference` flag is an SGLang feature, not platform-specific. Since Modal runs SGLang v0.5.6 natively, the flag is fully supported. SGLang's deterministic inference is compatible with chunked prefill, CUDA graphs, radix cache, and non-greedy sampling.

**Known issue to monitor:** There is an [open SGLang bug](https://github.com/sgl-project/sglang/issues/12232) reporting that Qwen3-235B-A22B-Thinking is not deterministic with `--enable-deterministic-inference`. This affects the Thinking variant specifically and may require testing during deployment. There is also an [open issue](https://github.com/sgl-project/sglang/issues/10785) about deterministic inference for MoE models in large tensor parallelism configurations — this does not apply to our single-GPU setup.

### Configuration Approach

SGLang on Modal is configured through three layers:

1. **Environment variables** — prefixed with `SGL_` or `SGLANG_`
2. **YAML configuration files** — loaded via `APP_LOCAL_CONFIG_PATH`
3. **Command-line arguments** — passed directly in the Python deployment script

---

## 4. Model Deployment Plan

### Target Configuration

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3-235B-A22B-GPTQ-Int4` |
| Fallback | `QuixiAI/Qwen3-235B-A22B-AWQ` |
| GPU | 1x H200 (141 GB) |
| Framework | SGLang v0.5.6 |
| Temperature | 0 |
| Deterministic | `--enable-deterministic-inference` |
| Quantization | GPTQ-Int4 (auto-detected by SGLang) |

### Deployment Steps

**Step 1: Create Modal Volume for model weights**

A Modal Volume stores the downloaded model weights persistently. On first run, weights download from HuggingFace (~125 GB). On subsequent runs, weights load from the volume at 1-2 GB/s.

```python
volume = modal.Volume.from_name("model-weights", create_if_missing=True)
```

**Step 2: Define the container image**

The container uses Modal's `Image.from_registry` to pull the official SGLang Docker image, then installs any additional dependencies.

```python
sglang_image = modal.Image.from_registry(
    "lmsysorg/sglang:v0.5.6-cu126",
    add_python="3.12",
).pip_install("huggingface_hub[hf_transfer]")
```

**Step 3: Define the SGLang server class**

```python
@app.cls(
    gpu="H200",
    image=sglang_image,
    volumes={"/models": volume},
    timeout=600,
)
class SGLangServer:
    @modal.enter()
    def start_server(self):
        # Launch SGLang with deterministic inference
        # Download weights to volume if not cached
        ...

    @modal.web_server(port=30000)
    def serve(self):
        ...
```

**Step 4: Deploy**

```bash
modal deploy infra/deploy_qwen3_next_endpoint.py
```

This creates a persistent HTTPS endpoint that auto-scales.

### GPTQ Consideration

Modal's official examples use FP8 quantization, not GPTQ. SGLang v0.5.6 supports GPTQ natively, but this specific combination (GPTQ-Int4 + H200 + Modal) has not been demonstrated in their documentation. If GPTQ-Int4 hits the same Marlin repacking OOM observed on RunPod (138.91GB out of 139.72GB with no headroom), the AWQ fallback should work without that issue.

---

## 5. Volumes and Cold Starts

### Volume Mechanics

- **Storage:** Modal Volumes are persistent network-attached storage
- **Speed:** 1-2 GB/s read throughput (vs. ~100 MB/s from HuggingFace download)
- **Cost:** No storage costs listed in Modal's pricing — appears to be included
- **No region lock:** Unlike RunPod network volumes, Modal Volumes are not tied to a specific GPU datacenter

### Cold Start Expectations

For a 125 GB model loading from a Modal Volume at 1-2 GB/s:

| Phase | Estimated Time |
|---|---|
| Container startup | ~10-30 seconds |
| Weight loading from volume | ~60-125 seconds |
| SGLang initialization | ~30-60 seconds |
| **Total cold start** | **~2-4 minutes** |

Modal's documentation notes that "booting up inference engines for large models takes minutes" and recommends `min_containers >= 1` for production to avoid cold starts. For Phase 0 testing, scale-to-zero is acceptable. For Phase 1 production (weekly scoring runs), the 2-4 minute cold start is tolerable since scoring itself takes ~2 minutes.

### Snapshot Optimization (Future)

Modal supports CPU + GPU memory snapshotting — saving the fully loaded model state and restoring it on container startup. This can reduce cold starts to seconds. This is an optimization for later phases, not required for initial deployment.

---

## 6. Cost Estimate

### Per-Run Cost

| Component | Duration | Cost |
|---|---|---|
| Cold start (weight loading + init) | ~3 minutes | ~$0.23 |
| Scoring inference (warm) | ~2 minutes | ~$0.15 |
| **Total per run** | **~5 minutes** | **~$0.38** |

### Monthly Cost (Weekly Scoring)

| Scenario | Runs/Month | Monthly Cost |
|---|---|---|
| Weekly scoring, scale-to-zero | 4 | ~$1.52 |
| Weekly + testing/debugging | 20 | ~$7.60 |
| Daily scoring | 30 | ~$11.40 |
| Min 1 container (always warm) | N/A | ~$3,270/month |

The scale-to-zero model with weekly scoring costs under $10/month. The $30/month free credit on the Starter plan covers this entirely during development and early production.

**Note:** Keeping a minimum container running 24/7 ($3,270/month) is not necessary for the current use case. Cold starts of 2-4 minutes are acceptable for a weekly scoring pipeline that is not latency-sensitive.

### Comparison to RunPod

| | RunPod (if it worked) | Modal |
|---|---|---|
| H200/hr | $3.99 | $4.54 |
| Per scoring run | ~$0.33 | ~$0.38 |
| Monthly (weekly scoring) | ~$1.32 | ~$1.52 |
| Free credits | None | $30/month |

Modal is ~15% more expensive per GPU-hour but the $30/month free credits more than offset this at the expected usage level.

---

## 7. Prerequisites Checklist

Before deployment, the following must be in place:

- [x] **Modal account** — sign up at [modal.com](https://modal.com) (Starter plan, free)
- [x] **Modal CLI installed** — `pipx install modal` (on macOS with Homebrew-managed Python, `pipx` avoids the `externally-managed-environment` error that blocks `pip install`)
- [x] **Modal authentication** — `modal setup` (browser-based token auth, saves token to `~/.modal/`)
- [x] **CLI verified** — ran the "hello world" example (`modal run get_started.py`) to confirm the account and CLI work
- [ ] **HuggingFace token** — set as a Modal Secret for downloading gated models (if needed for the specific model variant)
- [ ] **Deployment script** — Python script defining the SGLang server, volume, and endpoint configuration
- [ ] **Volume created** — first run will create the volume and download model weights (~125 GB, one-time)

No quota requests, GPU approvals, or support tickets are expected for H200 access on the Starter plan. If GPU concurrency limits become an issue, upgrading to the Team plan ($250/month) increases the limit from 10 to 50.

### Team Workspace Setup

For production use, a Modal Team workspace should be created so that billing, secrets, and deployments are owned by the organization rather than a personal account. To set this up:

1. Go to [modal.com/settings](https://modal.com/settings) and create a new workspace with the organization name
2. Add a payment method to the workspace (credit card or invoice billing)
3. Invite team members — each member authenticates with `modal setup` and selects the team workspace
4. Deployments, volumes, and secrets created under the team workspace are shared and billed to the organization

This should be done before deploying the scoring endpoint so that infrastructure is not tied to an individual account.

---

## 8. Risk Assessment

### Low Risk

| Risk | Mitigation |
|---|---|
| H200 temporarily unavailable | Modal has multiple GPU regions; B200 (180 GB) is a viable fallback GPU |
| Cold start too slow | Acceptable for weekly scoring; snapshot optimization available later |
| SGLang version mismatch | Modal uses v0.5.6, well-maintained; can pin specific versions via Docker image |

### Medium Risk

| Risk | Mitigation |
|---|---|
| GPTQ-Int4 OOM during Marlin repacking | Same issue as RunPod — if it occurs, fall back to AWQ quantization |
| Deterministic inference not fully stable for MoE models | Known open issues in SGLang for Qwen3-235B specifically; test early, report bugs upstream if needed |
| Starter plan GPU concurrency limit (10) | Sufficient for current use; upgrade to Team plan if needed |

### Low Probability, High Impact

| Risk | Mitigation |
|---|---|
| Modal deprecates H200 or changes pricing significantly | Infrastructure is code — can migrate to another provider (Baseten, Cerebrium) with similar SGLang wrappers |
| SGLang deterministic inference is fundamentally broken for Qwen3-235B MoE | This would be a model/framework issue, not platform-specific. Would affect any provider. Escalate to SGLang maintainers |

### Alternative Platforms (if Modal Fails)

If Modal proves unviable, the following platforms support SGLang with H200 GPUs:

| Platform | SGLang Support | H200 | Serverless |
|---|---|---|---|
| **Baseten** | Via Truss framework | Yes | Yes |
| **Cerebrium** | Custom containers | Yes | Yes |
| **Azure Container Apps** | Custom containers | Limited | Yes |
| **Self-hosted (Vultr/Hetzner)** | Full control | Depends on availability | No (always-on) |

---

## Recommendation: Go

Modal is viable for the Dynamic UNL scoring pipeline. The platform provides:

1. H200 GPUs at competitive pricing with per-second billing
2. Native SGLang v0.5.6 support with official examples for large models
3. Deterministic inference compatibility (`--enable-deterministic-inference` is an SGLang flag, fully supported)
4. Persistent volume caching for fast model loading
5. Python-native infrastructure — reproducible, version-controlled deployments
6. $30/month free credits covering the expected usage during development

The two medium risks (GPTQ OOM and MoE determinism) are SGLang-level issues that would affect any deployment platform, not Modal-specific problems. Both have viable mitigations.

**Proposed next step:** Deploy `Qwen/Qwen3-235B-A22B-GPTQ-Int4` on Modal with a single H200, `--enable-deterministic-inference`, and temperature 0. Run the same scoring prompt used in the OpenRouter benchmarks to validate output quality and measure latency.
