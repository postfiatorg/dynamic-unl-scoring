# RunPod Serverless Is Not Viable for SGLang Deployment

Summary of deployment attempts over March 11-12, 2026. After more than a full day of debugging across multiple configurations, models, and approaches — including forking and publishing a custom Docker image — it was not possible to get a working SGLang serverless endpoint on RunPod. Community reports confirm these are known, unresolved platform issues.

---

## Why SGLang on Serverless Is Required

The Dynamic UNL scoring pipeline requires:

- **SGLang specifically** — it is the only framework that supports `--enable-deterministic-inference`, which is needed for cross-validator reproducibility in Phase 2
- **Serverless specifically** — scoring runs once per round (minutes of GPU time per day), so paying for a persistent GPU 24/7 ($2,870/month) is not justifiable
- **Single H200 GPU** — the model (Qwen3-235B-A22B at GPTQ-Int4, ~125GB) fits on one H200 (141GB VRAM), and single-GPU execution is required for deterministic output

---

## What Was Tried

### Attempt 1: Official SGLang Template (v1.2.0)

Used RunPod's built-in SGLang template (the latest version available in their UI) with `QuixiAI/Qwen3-235B-A22B-AWQ` on a single H200.

**Result:** Container crashed immediately on startup.

Two errors in the logs:

1. `CUDA unknown error (error 999)` — the template's base image (`sglang:v0.4.6-cu124`) ships an outdated CUDA toolkit incompatible with H200 GPUs
2. `ModuleNotFoundError: No module named 'vllm'` — SGLang v0.4.6 tries to import quantization utilities from vllm, which is not installed in the container

This is a bug in RunPod's official template. The template has not been updated since August 2025, despite the upstream repository having released v2.0.2 in November 2025 with fixes for both issues.

### Attempt 1b: Community Fork with vLLM Fix

A [community fork](https://github.com/zalaa17/worker-sglang-with-vllm) created by another user who hit the same `No module named 'vllm'` error was also tested. Their fix was to add `vllm==0.8.4` to the dependencies. However, this fork still uses the same SGLang v0.4.6 base image with CUDA 12.4, so while it patches the missing import, it does not fix the CUDA 999 error on H200 GPUs. The existence of this fork further confirms the official template is broken — other users are independently working around the same bugs.

### Attempt 2: Custom Docker Image (pft-sglang)

Since neither the official template nor the community fix addressed both errors, the upstream `runpod-workers/worker-sglang` repository was forked, upgraded to SGLang v0.5.2 with CUDA 12.6 (H200-compatible), cleaned of dead code, and published as a custom image to Docker Hub (`agtipft/pft-sglang:latest`) with automated CI/CD.

Repository: [github.com/postfiatorg/pft-sglang](https://github.com/postfiatorg/pft-sglang)

This resolved the CUDA and vllm errors. The container started successfully.

### Attempt 3: GPTQ-Int4 on Custom Image

Deployed `Qwen/Qwen3-235B-A22B-GPTQ-Int4` (the official Qwen quantization, preferred for production) using the custom image.

**Result:** Out of memory during model loading.

The model weights loaded successfully (138.91GB of 139.72GB allocated), but the GPTQ-to-Marlin kernel repacking step needed an additional 18MB of working memory and failed. The model technically fits, but there is no headroom for the loading transformation.

Setting `MEM_FRACTION_STATIC=0.85` to reduce SGLang's KV cache reservation did not help.

### Attempt 4: AWQ on Custom Image

Switched to `QuixiAI/Qwen3-235B-A22B-AWQ` to avoid the Marlin repacking OOM. Set container disk to 100GB.

**Result:** Worker stuck at "Initializing" indefinitely. Logs showed:

```
image ready, initializing model files
image ready, model not found
```

No further progress. No error message. No model download activity. Worker eventually marked as "throttled" by RunPod.

### Attempt 5: AWQ with Environment Variable Overrides

The issue was suspected to be `HF_HOME` pointing to `/runpod-volume/` (a path that does not exist without a network volume). Environment variables were added to redirect the cache:

- `HF_HOME=/tmp/huggingface-cache`
- `HUGGINGFACE_HUB_CACHE=/tmp/huggingface-cache`

**Result:** Same behavior. Worker stuck at "Initializing", logs show "model not found".

### Attempt 6: AWQ with 200GB Container Disk

Increased container disk from 100GB to 200GB (model weights are ~120GB).

**Result:** Same behavior. "Initializing model files" followed by "model not found", no progress.

### Attempt 7: Small Model Sanity Check

To rule out model size as the issue, `Qwen/Qwen2.5-7B-Instruct-AWQ` was deployed — a 7B model that fits easily on any GPU.

**Result:** Same behavior. Worker stuck at "Initializing", "model not found". This confirmed the problem is not model-specific but a platform-level issue with SGLang serverless on RunPod.

### Attempt 8: vLLM Serverless (Control Test)

To determine whether the problem was environment-specific or SGLang-specific on the platform, two models were deployed using RunPod's **vLLM** serverless template instead:

- `Qwen/Qwen2.5-7B-Instruct-AWQ`
- `Qwen/Qwen2.5-0.5B`

**Result:** Both deployed and ran successfully. This confirms that RunPod serverless works with vLLM but is broken specifically for SGLang. However, vLLM does not support `--enable-deterministic-inference`, which is a hard requirement for Phase 2 cross-validator reproducibility. vLLM cannot be used as a substitute.

### Network Volume — Not an Option

Creating a network volume requires H200 availability in the selected datacenter. At time of testing, all H200-capable datacenters showed "N/A" availability, making it impossible to create a volume in a region where H200 workers can mount it.

---

## General Platform Instability

Beyond the SGLang-specific issues, general reliability problems were encountered with the RunPod serverless platform:

- **Inconsistent UI behavior** — clicking buttons would sometimes produce "unknown error" dialogs that resolved on retry without any change
- **Configuration sensitivity** — adding a single environment variable to an otherwise working endpoint could cause it to fail with no clear error
- **Non-reproducible deployments** — the same configuration that worked once would fail on a subsequent attempt with identical settings
- **Opaque worker states** — workers would enter "throttled" or perpetual "Initializing" states with no actionable error in the logs
- **No useful error messages** — the platform reports "model not found" without specifying what it tried, where it looked, or why it failed

---

## Community Reports Confirm These Issues

These problems are not isolated. Recent community reports document the same patterns:

- **SGLang works in pods, fails in serverless** — multiple users report that identical Docker images and configurations work perfectly in RunPod pods but fail in serverless, with API routes returning 404 errors
- **Serverless does not reuse SGLang server instances** — each request spawns a new server process instead of routing to the running one, eliminating SGLang's batching optimizations and causing 10x slower response times (30s vs 3s)
- **Workers stuck initializing** — users report workers permanently stuck in "Initializing" with no logs and no error, identical to the behavior observed here
- **H200 availability issues** — benchmark testing with Qwen3-235B-A22B-FP8 found "extremely long queues" making serverless unreliable for large models

The RunPod team has acknowledged SGLang serverless limitations but has not shipped fixes. The official SGLang template remains at v1.2.0 (August 2025) despite upstream fixes being available since November 2025.

Sources:

- [SGLang serverless 404 errors, works in pod but not serverless](https://www.answeroverflow.com/m/1275353840073441362)
- [SGLang worker fails to initialize, model not found](https://www.answeroverflow.com/m/1469205543204683948)
- [Serverless endpoint stuck at initializing](https://www.answeroverflow.com/m/1470778923406069842)
- [SGLang serverless configuration issues](https://www.answeroverflow.com/m/1470069877913030798)
- [Workers stuck, no logs, no error messages](https://www.answeroverflow.com/m/1443833923485433866)
- [First attempt at serverless — "Initializing" for a long time](https://www.answeroverflow.com/m/1305055599394033664)

---

## Recommendation: Evaluate Modal as an Alternative

[Modal](https://modal.com) is a serverless GPU platform with characteristics that directly address every issue encountered on RunPod:

| Problem on RunPod | Modal's Approach |
|---|---|
| Broken SGLang template, no updates since Aug 2025 | First-class SGLang support with maintained, documented examples |
| "Model not found" with no explanation | Model weights cached in Modal Volumes, loaded in seconds on cold start |
| H200 network volume unavailable | H200 and B200 GPUs available, volumes not region-locked to GPU type |
| Configuration via fragile web UI | Infrastructure defined in Python code — version-controlled, reproducible |
| Opaque errors, non-reproducible deployments | Deterministic deployments from code, clear error reporting |
| No batching optimization in serverless | Persistent server instances with proper request routing |

Modal maintains official examples for deploying very large models (DeepSeek V3, GLM 4.7, Kimi-K2) on H200 GPUs using SGLang, including MoE architectures similar to Qwen3-235B-A22B.

**Proposed next step:** Evaluate Modal with the same model and configuration. If it works, adopt it for Phase 1 production deployment. The `pft-sglang` repository and SGLang configuration work already completed is reusable — only the deployment wrapper changes.

---

## Cost Comparison

| | RunPod Serverless | RunPod Pod | Modal Serverless |
|---|---|---|---|
| H200 hourly rate | ~$3.99/hr | ~$3.99/hr | ~$4.55/hr |
| Idle cost | $0 | $2,870/month | $0 |
| Cold start | Broken (never completes) | N/A (always on) | Seconds (cached weights) |
| SGLang support | Broken on serverless | Works on pods | Works, officially supported |
| Deterministic inference | Untestable | Works but not serverless | Supported |

---

## Conclusion

After eight deployment attempts across two days, using the official template, a community fork, and a custom-built Docker image, with multiple models and configurations, SGLang cannot be made to run on RunPod serverless. The platform has known, unresolved issues with SGLang in serverless mode, confirmed by community reports. Continuing to debug RunPod is not a productive use of time.

Modal should be evaluated as the deployment platform for Phase 1. If it works, it becomes the production target. The model selection, prompt design, and scoring pipeline work from Phase 0 carries over unchanged — only the infrastructure layer changes.
