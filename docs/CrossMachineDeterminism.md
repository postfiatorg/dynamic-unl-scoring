# Same-GPU Cross-Machine Determinism Test — SGLang on Modal

Run 2026-08-21. Question under test: **does SGLang's deterministic inference
profile produce bit-identical outputs on two different physical machines when
the GPU setup is identical?**

## Why this test exists

The Vast.ai multi-GPU experiment (2026-08-20, `determinism-test/RESULTS.md` in
the `vast-multigpu-determinism` worktree) established at TP=4 that
`Qwen/Qwen3.5-122B-A10B-FP8` is bit-deterministic *within* one machine on the
fresh-prefill path, but its two machines **diverged from each other**. That
comparison was confounded: machine 1 ran 4× H100 NVL (94 GB, driver 595.71.05)
and machine 2 ran 4× H100 SXM (80 GB, driver 580.126.20) — a different GPU
variant *and* a different driver. Only one 4×NVL machine existed on the Vast
marketplace, so a same-SKU pair could not be rented there.

This test removes the confound. If two machines with byte-identical GPU
name/memory/driver/CUDA still diverge, cross-machine reproduction is broken at
a deeper level. If they agree, the Vast divergence is attributable to the
variant/driver difference — and a multi-GPU verification contract that pins
the exact GPU variant (as the execution manifest already pins runtime and
revision) becomes empirically defensible.

## Test design

### Model and runtime (identical on both machines)

| Item | Value |
|---|---|
| Model | `Qwen/Qwen3.5-122B-A10B-FP8`, HF revision `a099dee70ccfcd8d5dda56aaa0b60cb8ecadabc9` |
| Weights | One shared Modal volume (`determinism-test-qwen35-122b-weights`) — both machines read the same bytes |
| Image | `lmsysorg/sglang:nightly-dev-cu13-20260817-d91c3682@sha256:fa8774dd…` (pinned digest; same image family as the Qwen3.8 candidate evaluation and the Vast experiment) |
| GPUs | 4× H100 (`H100!:4` — the `!` forbids Modal from silently substituting another GPU class), TP=4 |
| Launch | `--enable-deterministic-inference --attention-backend fa3 --disable-radix-cache --mem-fraction-static 0.85 --chunked-prefill-size 4096 --max-running-requests 1 --trust-remote-code` |
| Env | `SGLANG_BATCH_INVARIANT_OPS_ENABLE_MM_DEEPGEMM=0` — without it the server crashes at boot at TP=4 on this model (DeepGEMM TMA minimum-shape error); routes the batch-invariant matmul to its Triton path, which is still batch-invariant |
| Serving | `127.0.0.1` only, requests sent from inside the same container — no public endpoint, no stray traffic (mirrors the Vast protocol's SSH-only isolation) |

Deviation from the Vast launch line: `--model-path` points at the shared
volume snapshot instead of the HF repo id, with `--served-model-name
Qwen/Qwen3.5-122B-A10B-FP8` keeping the wire payloads unchanged. Semantics
identical; it additionally guarantees both machines serve the same weight
bytes.

### The machine-pair guarantee

Modal does not let you choose physical machines, so the harness proves the
pair instead of assuming it. Two containers are provisioned **concurrently**;
each captures a hardware fingerprint (GPU name, memory, driver, CUDA, UUIDs,
serials, VBIOS, PCI bus ids, module IDs, boot_id, uptime, CPU, kernel) and
then blocks — no server boot, no inference — until the driver has compared
the fingerprints and issued a go/abort decision:

- **Identical setup required:** GPU name, memory size, driver version, CUDA
  version equal across both machines, 4 GPUs each.
- **Distinct machines required:** GPU UUID and serial sets disjoint,
  different `boot_id`, and no same-host signature (near-identical host uptime
  combined with complementary GPU module IDs — the pattern of one 8-GPU host
  split 4+4 between the two containers).

An invalid pair aborts the cheaper container and provisions a replacement
(up to 4 attempts) before any GPU-hours are spent on inference.

### Inputs (frozen before the run)

Four wire payloads, frozen in
`docs/crossmachine-determinism-evidence/inputs/wire/` with SHA-256 recorded
in `manifest.json`. All use `temperature: 0` and `enable_thinking: false`.

| Input | Size | Purpose | sha256 (prefix) |
|---|---|---|---|
| `simple` | 93-char prompt, max_tokens 512 | Small matrix shapes — the territory of the DeepGEMM minimum-shape boot crash | `38666c90…` |
| `round19` | Frozen testnet round 19 `model_request.json`, 49,727 prompt chars, max_tokens 16,384 | Production shape and the anchor to prior evidence — the wire payload is verified byte-identical to what the Vast Stage 1 machines received (extra_body hoisted, model field swapped, `method` dropped) | `b37f6b60…` |
| `moderate` | ~18k chars (seeded synthetic weather-station records + analysis task), max_tokens 2,048 | Two-chunk prefill (chunked-prefill-size 4096) | `74b66d3e…` |
| `long` | ~102k chars (~30k tokens synthetic records + detailed report task), max_tokens 8,192 | Many-chunk prefill and a long generation — divergence compounds with output length | `770458e1…` |

Synthetic inputs were generated once by `scripts/make_synthetic_inputs.py`
(seed 20260821) and are frozen files from that point; the model's 262,144-token
context bounds every input + output with wide margin. Fingerprint rule
throughout: SHA-256 of `choices[0].message.content` — the same rule as the
Vast experiment and the Qwen3.8 evaluations.

### Battery (per machine)

| Phase | Runs |
|---|---|
| boot1 | 2 passes over [simple, round19, moderate, long] — repeats separated in time, not back-to-back |
| server restart (same container, same GPUs) | — |
| boot2 | 1 pass over the four inputs |

12 requests per machine, 24 total. Radix cache is disabled, so every run is
the fresh-prefill path — the production topology (one request per cold boot),
and the path the Vast experiment showed to be per-machine stable.

### Verdict rule (stated before results)

Per input:

- **PASS** — all 6 fingerprints (3 per machine) identical.
- **DIVERGENT-CROSS-MACHINE** — each machine internally stable, but the two
  disagree. With the setup proven identical, this would mean cross-machine
  determinism fails even under SKU/driver parity.
- **UNSTABLE** — a machine disagrees with itself. Would contradict the Vast
  per-machine finding and dominate every other conclusion.

`finish_reason` is recorded on every run; a `length` finish marks a
truncated generation (still a valid determinism probe, but flagged).

## Execution log

Session `session-20260821T091816Z` (all artifacts under
`docs/crossmachine-determinism-evidence/`).

- Weights (127 GB) downloaded once to the shared volume in ~10 min, pinned
  revision `a099dee7…`.
- Machine pair valid on the **first** provisioning attempt: both containers
  reported 4× NVIDIA H100 80GB HBM3 (SXM), 81,559 MiB, driver **580.95.05**,
  CUDA 13.0, VBIOS 96.00.CF.00.01 — with fully disjoint GPU serial and UUID
  sets and distinct boot ids. GO issued; batteries started.
- Both servers booted healthy in ~7 min (boot1: 436 s / 431 s), restarted
  cleanly for boot2 (126 s / 156 s). All 24 requests returned HTTP 200.
- Sandbox visibility caveat found during the run: Modal's gVisor sandbox
  masks PCI bus ids, GPU module IDs, and host CPU identity, so
  distinct-physical-host proof cannot come from host identifiers alone.
  Response: a **third machine** (m3) was added, gated on its 4 GPU serials
  being disjoint from all 8 already seen — 12 distinct physical H100s cannot
  belong to one 8-GPU host, so ≥2 distinct physical machines are proven by
  pigeonhole regardless of what the sandbox hides.

## Results

### Two-machine battery (m1 vs m2)

**PASS on every input.** All fingerprints identical across both machines,
both passes, and the server restart — 24/24 runs.

| Input | Prompt tok | Completion tok | finish | Content sha256 | m1 runs | m2 runs |
|---|---|---|---|---|---|---|
| simple | 32 | 102 | stop | `c38edf1400fca7fc…` | 3/3 identical | 3/3 identical |
| round19 | 14,434 | 7,137 | stop | `1944a647d3e23163…` | 3/3 identical | 3/3 identical |
| moderate | 7,079 | 429 | stop | `9291a232fe2c54d1…` | 3/3 identical | 3/3 identical |
| long | 40,466 | 8,192 | length (cap, deterministic truncation) | `f06d518783915fd1…` | 3/3 identical | 3/3 identical |

Per-input latencies were near-identical across machines (e.g. round19:
93.0–93.4 s on both; long: 162.9–163.7 s on both).

### Cross-platform anchor match

The round19 fingerprint `1944a647d3e23163…` (7,137 completion tokens) is
**byte-identical to the Vast.ai H100 SXM machine's** result from 2026-08-20
(`s1-qwen35-m2`, driver 580.126.20). That makes three physical machines,
two providers (Vast.ai marketplace, Modal), and two driver minors
(580.126.20 / 580.95.05) producing the same bits on the same GPU variant —
while the Vast H100 **NVL** machine (driver 595.71.05) remains the sole
divergent result (`597768…`).

### Third machine (m3, pigeonhole leg)

m3 was intended to run concurrently with m1/m2, but Modal's workspace GPU
cap queued it until the pair's GPUs freed, so it ran immediately **after**
them on the same session. The proof survives sequential scheduling: m3's
gate required its 4 GPU serials to be disjoint from all 8 already seen, and
they were — 12 distinct physical H100s total. Twelve distinct GPUs cannot
belong to one 8-GPU host, so **at least two distinct physical machines are
involved by pigeonhole**, whichever way the three 4-GPU slices were placed.

m3's setup matched m1/m2 exactly (4× H100 80GB HBM3, 81,559 MiB, driver
580.95.05, CUDA 13.0, VBIOS 96.00.CF.00.01; boot_id `aa59dffd…`, serials
`…066910/004464/075743/004719`), and its full 12-run battery — same phases,
same restart — produced **the same four fingerprints as m1 and m2 on every
run**. Its latencies matched too (round19 93.7 s; long 164.0–164.1 s).

### Final matrix

36 runs, 3 machines, 4 inputs, 2 boots per machine — one hash per input:

| Input | m1 | m2 | m3 | Verdict |
|---|---|---|---|---|
| simple | `c38edf14…` ×3 | `c38edf14…` ×3 | `c38edf14…` ×3 | **PASS** |
| round19 | `1944a647…` ×3 | `1944a647…` ×3 | `1944a647…` ×3 | **PASS** |
| moderate | `9291a232…` ×3 | `9291a232…` ×3 | `9291a232…` ×3 | **PASS** |
| long | `f06d5187…` ×3 | `f06d5187…` ×3 | `f06d5187…` ×3 | **PASS** |

All 36 requests returned HTTP 200; no run needed a retry; the machine pair
and the third machine each validated on their first provisioning attempt.

## Conclusions

1. **Same-setup cross-machine determinism holds empirically.** On identical
   4× H100 SXM (80GB HBM3) machines — same driver, CUDA, VBIOS, image
   digest, weights bytes, and launch profile — SGLang's deterministic
   inference at TP=4 produced bit-identical outputs across at least two
   (almost certainly three) distinct physical machines, on all four input
   shapes, across server restarts, 36/36.

2. **The result extends across providers and driver minors.** The round19
   fingerprint `1944a647…` reproduces the Vast.ai H100 SXM result from
   2026-08-20 exactly, despite a different provider stack and a different
   580-series driver minor (580.126.20 vs 580.95.05). Same-variant
   reproduction is therefore not an artifact of one provider's fleet.

3. **The Vast Stage 1 divergence is now bounded to the variant/driver-major
   difference, not machine identity.** With variant and driver held equal,
   machines agree; the one divergent machine (H100 NVL, driver 595.71.05)
   differed in both GPU variant and driver major, and at least one of those
   is the cause. "H100-class" is demonstrably not a sufficient pin;
   `NVIDIA H100 80GB HBM3` + driver series is the empirically supported
   contract unit.

4. **Consequence for the governance pool's single-GPU constraint.** The
   constraint's original justification — multi-GPU determinism is folklore —
   no longer holds as stated: TP=4 fresh-prefill determinism is now
   demonstrated within a machine, across machines, and across providers,
   *provided the execution manifest pins the exact GPU variant* (as it
   already pins image digest and model revision). A relaxation would need
   the verification contract to add a GPU-variant pin (and treat the driver
   series as part of the runtime profile), plus per-model evidence — this
   test certifies the engine path and this model, not every candidate
   (determinism remains a per-model property, per the Qwen3.8 record).

5. **Scope boundaries.** Evidence covers: this model (Qwen3.5-122B-A10B-FP8),
   TP=4, the fresh-prefill path (radix cache off), the pinned 20260817 image,
   the DeepGEMM-MM Triton remediation, H100 SXM, driver series 580. Not
   covered: the cache-hit path (known to differ from fresh prefill on this
   engine family), other TP degrees, other GPU classes, driver-major
   variation on the same variant, and other models. The `long` input ends at
   its 8,192-token cap (`finish_reason: length`) — a deterministic
   truncation, identical everywhere, so it functions as a valid probe of a
   maximal-length generation.

## Cost and cleanup

Approximate GPU spend: three 4× H100 containers at ~20–30 billed minutes
each ≈ **$20–30** (Modal H100 ≈ $3.95/GPU-hr), plus a negligible CPU-only
weights download. All containers exited at battery end; no deployed apps,
endpoints, or scheduled functions remain. The coordination Dict and the 127 GB weights volume
`determinism-test-qwen35-122b-weights` were both deleted after the run
(operator decision: no reproduction needed). Re-running the test would
re-download the weights (~10 min) via
`modal run scripts/samegpu_determinism_test.py::download_weights`.

## Artifacts

Evidence root: `docs/crossmachine-determinism-evidence/`.

- `inputs/wire/` — the four frozen wire payloads + `manifest.json` hashes
- `inputs/round19_model_request.json` — the frozen round 19 request as
  fetched, before the wire conversion
- `results/session-20260821T091816Z/` — fingerprints per attempt,
  `machine-m{1,2,3}.json` (full raw responses, usage, latencies, server log
  tails), `comparison.json`
- `session.log`, `probe_third.log`, `download.log` — run transcripts
- `scripts/samegpu_determinism_test.py` — the harness (fingerprint gate,
  battery, verdict)
- `scripts/make_synthetic_inputs.py` — provenance for the synthetic inputs
  (seeded)
