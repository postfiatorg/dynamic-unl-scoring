# Self-Hosted Deployment: Qwen3-Next-80B-A3B on Modal

Following model selection (see [Round2Analysis.md](Round2Analysis.md)), the next step was deploying `Qwen3-Next-80B-A3B-Instruct-FP8` on a self-hosted SGLang endpoint with deterministic inference. Two platforms were tested: RunPod and Modal.

---

## RunPod: Dead End

RunPod was tested first since a deployment guide already existed for the previous model (see [RunPodDeployment.md](RunPodDeployment.md)).

**Result:** SGLang crashed immediately during model loading.

```
KeyError: 'model.layers.8.linear_attn.in_proj_qkvz.weight_scale_inv'
```

The error is a model architecture mismatch. Qwen3-Next uses a Mamba-2 hybrid architecture with linear attention layers (`linear_attn`, `in_proj_qkvz`) that the SGLang version bundled in RunPod's serverless runtime does not recognize. RunPod's SGLang image is frozen at an older version, and there is no way to specify a custom SGLang version on their serverless platform.

This is the same fundamental RunPod limitation documented in [WhyNotRunPodServerless.md](WhyNotRunPodServerless.md) — the platform does not support custom SGLang builds. Combined with the previous 9 failed deployment attempts, RunPod is not viable for this project.

**Decision:** RunPod is permanently dropped as a deployment option.

---

## Modal: Partial Success, Then OOM

Modal uses the deployment script at `infra/modal/deploy_endpoint.py` with SGLang v0.5.6, FP8 quantization, and `--enable-deterministic-inference` on a single H200.

### What Worked

The model loaded successfully on H200 and served small prompts:

| Metric | Value |
|---|---|
| Model VRAM | ~75 GB weights + ~36 GB Mamba cache + ~14 GB KV cache |
| Total VRAM used | ~127 GB of 141 GB |
| Free VRAM after loading | ~12 GB |
| Inference throughput | 131-133 tokens/s (after warmup) |
| Cold start time | ~15 minutes (weight loading + DeepGEMM JIT + CUDA graph capture) |

Simple queries ("Hello, who are you?") with 14 input tokens returned correct responses in seconds once warm.

### What Failed

The full scoring prompt (~8192 tokens, 42 validators) crashed the server on every attempt. Five consecutive scoring runs all returned empty responses.

**Error from Modal logs:**

```
RuntimeError: Buffer overflow when allocating memory for batch_prefill_tmp_s
with size 8388608 and alignment 16, but only 0 bytes available in
AlignedAllocator. Increase the workspace buffer size.
```

Each crash killed the SGLang process, which triggered a Modal container restart, which triggered another 15-minute cold start, which then hit the same OOM on the next request. The five scoring runs consumed ~75 minutes of GPU time producing nothing.

### Root Cause: FlashInfer Workspace Buffer

SGLang allocates a fixed-size GPU workspace buffer for FlashInfer's attention computation. The default is 2 GB, but **SGLang overrides this to 512 MB specifically for Qwen3 model architectures** (in `flashinfer_backend.py`). This 512 MB workspace is sufficient for small prefills but overflows when processing the ~8192-token scoring prompt.

The issue is compounded by memory pressure from three sources:
1. **Mamba-2 state cache** (~36 GB) — unique to hybrid Mamba models like Qwen3-Next
2. **CUDA graph capture** — pre-allocates memory for graph replay buffers during warmup
3. **KV cache pool** — SGLang pre-allocates 90% of remaining memory by default

After all pre-allocations, there is effectively zero free VRAM for the FlashInfer workspace to grow into during large prefills.

### Additional Issue: Cold Start Time

Every container start requires ~15 minutes:
- **DeepGEMM JIT compilation** (~10 min): FP8 matrix multiplication kernels are compiled from scratch each time. These CUDA kernels are model-specific and must be compiled on the target GPU architecture.
- **CUDA graph capture** (~5 min): SGLang captures optimized execution graphs for various batch sizes.
- **Weight loading** (<1 min): Fast — weights are cached in a Modal Volume.

The 5-minute `scaledown_window` means the container scales to zero between requests during development/testing, triggering a full cold start on every interaction.

---

## Fixes Required

### Fix 1: FlashInfer Workspace Buffer

Override the 512 MB Qwen3 default by setting the environment variable before server launch:

```
SGLANG_FLASHINFER_WORKSPACE_SIZE=2147483648  # 2 GB
```

### Fix 2: Memory Headroom

Reduce SGLang's static memory pre-allocation to leave more headroom for the workspace buffer and runtime allocations:

```
--mem-fraction-static 0.75    # Default: 0.90 — reserves 90% for weights + KV/Mamba cache
--chunked-prefill-size 4096   # Default: 8192 — smaller chunks = smaller workspace needs
--max-running-requests 4      # Limit concurrent requests to reduce KV/Mamba cache pressure
```

### Fix 3: DeepGEMM Pre-Compilation

Pre-compile kernels during the Docker image build so they are cached before serving starts:

```python
sglang_image = sglang_image.run_commands([
    "python3 -m sglang.compile_deep_gemm "
    "--model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 --tp 1 --trust-remote-code"
])
```

This adds ~10 minutes to the image build (one-time cost) but eliminates the ~10-minute JIT compilation from every cold start. Cold start drops from ~15 min to ~5 min (CUDA graph capture only).

### Fix 4: Scaledown Window

Increase `scaledown_window` from 5 to 20 minutes during active scoring sessions so the container stays warm between runs. This prevents the cold start loop where each failed request triggers a 15-minute restart before the next request can be served.

---

## Results After Fixes

After applying all four fixes and redeploying, the endpoint works correctly.

### Cold Start

DeepGEMM pre-compilation eliminated JIT warmup from cold starts. First request after deploy took ~116s (container startup + CUDA graph capture). Subsequent requests while warm: 1.4-2.9s.

### Determinism Confirmed (Small Inputs)

Repeated identical prompts produced bit-identical responses — same content, same token counts, same finish reason across all runs. Two examples tested:

| Prompt | Tokens In | Tokens Out | Time (warm) | Deterministic |
|---|---|---|---|---|
| "Hello, who are you?" | 14 | 79 | 1.4-2.9s | Yes — identical across 3 runs |
| "Sing me a song" | 12 | 256 | 2.6-2.8s | Yes — identical across 2 runs |

### Determinism Confirmed (Full Scoring Prompt)

The full scoring prompt (42 validators, ~15,291 tokens) was run 5 times. All 5 runs produced **bit-identical output** — same raw text, same scores, same token counts, same finish reason.

| Metric | Value |
|---|---|
| Runs | 5 |
| Validators scored | 42/42 (all runs) |
| Score range | 5-97 |
| Mean score | 85.31 |
| Prompt tokens | 15,291 |
| Completion tokens | 3,146 |
| Time (first run, cold) | 54.0s |
| Time (warm runs) | 42.7s |
| Cross-run score variance | 0 (all runs identical) |

Raw results: `results/modal/qwen3-next-80b-instruct/2026-03-13_12-35-32/run_1.json` through `run_5.json`.

This is stronger determinism than the OpenRouter benchmark (Round 2), which measured a 0.3 mean spread across runs. The self-hosted SGLang endpoint with `--enable-deterministic-inference` on a single H200 achieves perfect reproducibility.
