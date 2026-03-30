# Modal Deployment Attempts: Qwen3-235B-A22B on a Single GPU

Following the decision to move from RunPod to Modal (see `WhyNotRunPodServerless.md` and `ModalEvaluation.md`), six deployment attempts were made on March 12, 2026 to run Qwen3-235B-A22B with SGLang's `--enable-deterministic-inference` on a single GPU. All six failed due to GPU memory limitations during model loading.

This document records what was tried, why each attempt failed, what alternatives were evaluated, and what the situation means for the project going forward.

---

## The Core Problem: Marlin MoE Kernel Repacking

Every failure traces back to the same root cause. SGLang uses Marlin kernels to accelerate quantized inference. When loading a GPTQ or AWQ model, SGLang must convert ("repack") the quantized weights into Marlin's internal format. For MoE models like Qwen3-235B-A22B, this repacking step temporarily requires holding **both** the original weights and the new Marlin-format weights in GPU memory at the same time.

For Qwen3-235B-A22B:

- Original quantized weights (4-bit): ~138 GB
- Marlin-repacked weights accumulate as layers are converted
- Peak memory during repacking: ~178+ GB
- The repacking allocates 768 MB per MoE layer, and fails when free VRAM drops below that threshold

This is not a configuration issue. It is a fundamental memory constraint of the Marlin repacking process for models of this size. The [SGLang issue tracker](https://github.com/sgl-project/sglang/issues/8362) confirms this is a known problem.

---

## Deployment Attempts

All attempts used the deployment script at `infra/deploy_endpoint.py` with SGLang v0.5.6 (`lmsysorg/sglang:v0.5.6.post2-cu129-amd64-runtime`), model weights cached in a Modal Volume, and `--enable-deterministic-inference` enabled.

### Attempt 1: GPTQ-Int4 on H200

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3-235B-A22B-GPTQ-Int4` |
| GPU | H200 (141 GB total, 139.80 GB usable) |

SGLang loaded all 25 safetensor shards successfully. During `process_weights_after_loading()`, the GPTQ-to-Marlin repacking (`gptq_marlin_moe_repack`) attempted to allocate 768 MB but only 84 MB was free.

```
torch.OutOfMemoryError: Tried to allocate 768.00 MiB.
GPU 0 has a total capacity of 139.80 GiB of which 84.44 MiB is free.
Of the allocated memory 138.91 GiB is allocated by PyTorch.
```

Failed by ~684 MB.

### Attempt 2: AWQ on H200

| Setting | Value |
|---|---|
| Model | `QuixiAI/Qwen3-235B-A22B-AWQ` |
| GPU | H200 |

Same failure point, slightly different numbers. AWQ weights are marginally smaller than GPTQ, leaving 516 MB free — still not enough for the 768 MB Marlin repacking step.

```
torch.OutOfMemoryError: Tried to allocate 768.00 MiB.
Of the allocated memory 138.49 GiB is allocated by PyTorch, and 516.00 MiB is free.
```

Failed by ~252 MB.

### Attempt 3: AWQ on H200 with CPU Offloading

Added `--cpu-offload-gb 2` to the SGLang launch command, hoping to free GPU memory by offloading some layers to system RAM.

**Result:** Same OOM. The `cpu-offload-gb` flag offloads layers *after* loading completes, but the OOM occurs *during* `process_weights_after_loading()` — before offloading has a chance to run.

```
Of the allocated memory 138.53 GiB is allocated by PyTorch, and 460.00 MiB is free.
```

CPU offloading cannot help with this problem.

### Attempt 4: AWQ on B200

Switched to B200 (192 GB total, 178.35 GB usable) to get more VRAM headroom.

**Result:** New error. B200's default attention backend (`trtllm_mha`) is incompatible with SGLang's deterministic inference mode.

```
ValueError: Currently only ['flashinfer', 'fa3', 'triton'] attention backends
are supported for deterministic inference, but you explicitly specified 'trtllm_mha'.
```

Not a memory issue — a configuration incompatibility between B200 defaults and the deterministic inference flag.

### Attempt 5: AWQ on B200 with FlashAttention 3

Added `--attention-backend fa3` to override the B200 default. This resolved the attention backend error, but introduced a new problem.

SGLang auto-detected the AWQ model and set `quantization='awq'` (non-Marlin), which loads expert weights in full FP16 precision instead of keeping them at 4-bit. The logs showed this warning:

> Detected that the model can run with awq_marlin, however you specified quantization=awq explicitly, so forcing awq.

FP16 loading consumed 176.57 GB — nearly all of B200's 178.35 GB — and then OOM'd trying to allocate the next layer.

```
torch.OutOfMemoryError: Tried to allocate 1.50 GiB.
Of the allocated memory 176.57 GiB is allocated by PyTorch.
```

Non-Marlin AWQ is not viable for this model on any single GPU.

### Attempt 6: AWQ on B200 with Explicit Marlin Quantization

Added `--quantization awq_marlin` to force Marlin kernels instead of the non-Marlin fallback. This was expected to keep weights at 4-bit (~138 GB) and leave ~40 GB of headroom for the 768 MB repacking on B200.

**Result:** Still OOM. The Marlin repacking process iterates through layers, converting each one. Both the original and repacked weights coexist during conversion, and peak memory grew to 177.98 GB before hitting the 768 MB allocation.

```
torch.OutOfMemoryError: Tried to allocate 768.00 MiB.
GPU 0 has a total capacity of 178.35 GiB of which 358.88 MiB is free.
Of the allocated memory 177.03 GiB is allocated by PyTorch.
```

B200 got significantly further than H200 (repacked many layers before failing), but still ~410 MB short.

---

## Why Tensor Parallelism Is Not an Option

The natural response to "one GPU isn't enough" is to split across two GPUs. Modal supports multi-GPU configurations (`gpu="H200:2"` with `--tp 2`), and 2x H200 would give 282 GB total — more than enough for repacking.

The problem is determinism. Tensor parallelism requires AllReduce operations across GPUs to combine partial results. Floating-point addition is not associative (`(a + b) + c ≠ a + (b + c)` at the bit level), and NCCL's cross-GPU reductions do not guarantee execution order. For MoE models, expert routing across GPUs adds another source of non-determinism.

SGLang's `--enable-deterministic-inference` addresses single-GPU non-determinism (kernel launch order, CUDA graph scheduling). It does not and cannot make cross-GPU floating-point reductions deterministic. There is an [open SGLang issue](https://github.com/sgl-project/sglang/issues/10785) specifically about deterministic inference for MoE models with tensor parallelism.

Cross-validator reproducibility is a hard requirement for Phase 2. TP>1 cannot guarantee it.

---

## Alternative Models from Phase 0 Evaluation

The Phase 0 model evaluation (`Round1Analysis.md`) selected three candidates. All three were assessed for single-GPU feasibility.

### qwen3-235b-instruct

Same underlying architecture as qwen3-235b-thinking: 235B total parameters, 22B active, MoE. Uses the same quantized weights (GPTQ-Int4 or AWQ). Hits the identical Marlin repacking OOM. Not viable on any single GPU.

### minimax-m2.5

229B parameters (10B active), MoE with 256 experts. Unquantized: 457 GB. Even with AWQ 4-bit quantization, the model requires a minimum of **2x B200 or 4x H100** according to deployment guides. It would face the same Marlin repacking memory pressure as Qwen3-235B-A22B, and the same TP>1 determinism constraint applies.

### Summary

| Model | Total Params | Active Params | Min GPU (Quantized) | Single-GPU Viable |
|---|---|---|---|---|
| qwen3-235b-thinking | 235B | 22B | > 1x B200 | No |
| qwen3-235b-instruct | 235B | 22B | > 1x B200 | No |
| minimax-m2.5 | 229B | 10B | 2x B200 | No |

All three Phase 0 candidates are 229-235B MoE models. None fit on any single GPU available on Modal (or any other cloud provider) due to Marlin repacking peak memory requirements.

---

## Could the SGLang Marlin Fix Be Contributed?

The Marlin repacking OOM is a software limitation, not a hardware one. The fix would involve modifying SGLang's `process_weights_after_loading()` in `awq.py` / `gptq.py` to repack layers incrementally — freeing the original weights for each layer before allocating the next Marlin-format tensor, instead of holding everything in memory simultaneously.

This is a medium-difficulty change requiring familiarity with PyTorch memory management and Marlin kernel internals. It would take a few days of focused work and ~$10-20 in GPU credits for iterative testing. The fix could be contributed upstream as a PR to SGLang, since it affects everyone trying to run large MoE models on single GPUs.

The downside is maintaining a fork of SGLang (or waiting for the PR to merge) and rebuilding the Docker image for Modal deployments.

---

## Cost of These Attempts

All attempts ran on Modal's Starter plan ($30/month free credits). Each failed attempt consumed GPU time during model loading and SGLang's automatic retry loop (load weights → OOM → restart → load weights → OOM).

| GPU | Rate | Est. Time Per Attempt | Est. Cost |
|---|---|---|---|
| H200 | $4.54/hr | 5-10 min (loading + retries) | $0.40-$0.75 |
| B200 | $6.25/hr | 5-10 min (loading + retries) | $0.50-$1.05 |

Modal spawned multiple containers per attempt as part of its retry logic. Total spend across all attempts was approximately $25-28, exhausting the $30 monthly free credit allotment. The billing limit was hit before the final attempt could complete, requiring a budget increase.

---

## Where This Leaves the Project

The deployment script at `infra/deploy_endpoint.py` is complete and tested — it correctly builds the container image, caches model weights in a Modal Volume, and launches SGLang with the right configuration. The infrastructure works. The problem is that Qwen3-235B-A22B is too large for deterministic single-GPU inference on any currently available hardware.

The options going forward:

1. **Smaller model** — A model in the 30-70B parameter range (e.g., Qwen3-32B dense) would fit trivially on a single H200 with deterministic inference. Requires re-evaluating scoring quality against the Phase 0 benchmarks.

2. **Contribute the SGLang Marlin fix** — Modify the repacking to use less peak memory. If accepted upstream, Qwen3-235B-A22B becomes viable on a single B200. Requires SGLang internals expertise and time.

3. **Wait for SGLang or hardware improvements** — Future SGLang versions may optimize Marlin repacking. Future GPUs (GB300, B300) may offer enough single-GPU VRAM. No timeline for either.

4. **Accept TP=2 and empirically validate determinism** — Run the same prompt many times on 2x H200 and check for bit-identical outputs. If deterministic in practice (even if not guaranteed in theory), this unblocks the current model. Risk: non-determinism could surface unpredictably under different loads or inputs.
