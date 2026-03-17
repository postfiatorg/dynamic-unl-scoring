# Infrastructure — Modal Deployment

| File | Purpose |
|------|---------|
| `deploy_endpoint.py` | Deploys SGLang + Qwen3-Next-80B on a Modal H200 GPU |

---

## Modal CLI

### Install

```bash
pipx install modal    # or: pip install modal
modal --version
```

### Authenticate

```bash
modal setup                             # opens browser, select workspace
modal setup --profile <name>            # same, saves to a named profile
modal token set --profile <name>        # manual entry (prompts for token ID/secret)
modal token new --profile <name>        # generate new token via browser, save to profile
modal token info                        # show current token details
```

### Profiles

```bash
modal profile list                      # show all profiles, highlight active
modal profile current                   # show active profile
modal profile activate <name>           # switch active profile
```

---

## Deploy

```bash
modal deploy infra/deploy_endpoint.py   # persistent deployment
modal run infra/deploy_endpoint.py      # ephemeral smoke test (tears down when done)
```

First deploy on a workspace: ~18 min (downloads weights, compiles DeepGEMM). Subsequent deploys: ~3 seconds (cached image).

Endpoint URL format:

```
https://<workspace>--dynamic-unl-scoring-scoringendpoint-serve.modal.run
```

### Environment Variable Overrides

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCORING_MODEL_ID` | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` | HuggingFace model ID |
| `SCORING_GPU_TYPE` | `H200` | Modal GPU type |
| `SCORING_QUANTIZATION` | `fp8` | Quantization method |
| `SCORING_ATTENTION_BACKEND` | _(empty)_ | SGLang attention backend |
| `SCORING_TP` | `1` | Tensor parallelism (number of GPUs) |
| `SCORING_MEM_FRACTION` | `0.75` | GPU memory reserved for model + KV cache |
| `SCORING_CHUNKED_PREFILL` | `4096` | Input token chunk size |
| `SCORING_MAX_REQS` | `4` | Max concurrent requests |

```bash
SCORING_MODEL_ID="Qwen/SomeOtherModel" modal deploy infra/deploy_endpoint.py
```

---

## Score Validators

```bash
python scripts/score_validators.py --url https://<workspace>--dynamic-unl-scoring-scoringendpoint-serve.modal.run/v1
python scripts/query.py --url https://<workspace>--dynamic-unl-scoring-scoringendpoint-serve.modal.run/v1 --prompt "Hello"
```

---

## Manage

```bash
modal app list                              # list deployed/running apps
modal app logs dynamic-unl-scoring          # stream logs
modal app dashboard dynamic-unl-scoring     # open dashboard in browser
modal app history dynamic-unl-scoring       # deployment history
modal app stop dynamic-unl-scoring          # stop all containers (image/volume stay cached)
modal billing report                        # workspace billing info
```

### Volumes

```bash
modal volume list                           # list all volumes
modal volume ls scoring-model-weights       # list files in the volume
modal volume delete scoring-model-weights   # delete volume (forces full re-download on next deploy)
```

---

## Cold Starts

Endpoint scales to zero after 20 minutes of inactivity.

| Phase | Time |
|-------|------|
| Container startup + weight loading | ~2 min |
| CUDA graph capture | ~3 min |
| **Total** | **~5 min** |

---

## Switch Workspace

1. Confirm billing is set up on the target workspace (`modal billing report` or Modal dashboard)
2. `modal profile activate <target-profile>`
3. `modal deploy infra/deploy_endpoint.py`
4. `modal run infra/deploy_endpoint.py`
5. Update the endpoint URL wherever you use it
6. Tear down old deployment:
   ```bash
   modal profile activate <old-profile>
   modal app stop dynamic-unl-scoring
   ```

---

## Troubleshooting

**Deploy fails with permissions/billing error** — workspace owner needs to add a payment method (Modal dashboard > Settings > Plan & billing).

**OOM during image build** — DeepGEMM compilation requires an H200. If unavailable, retry later.

**Cold start >10 minutes** — likely corrupted weights. Fix:

```bash
modal volume delete scoring-model-weights
modal deploy infra/deploy_endpoint.py
```

**Scoring prompt OOMs at runtime** — FlashInfer workspace (2 GB) or memory fraction (0.75) may need adjustment. See comments in `deploy_endpoint.py`.
