# Infrastructure — Modal Deployment

This directory contains the Modal/SGLang deployment entrypoints. The shared implementation is intentionally separate from model-specific wrappers.

## Files

| File | Purpose |
|---|---|
| `deploy_endpoint.py` | Shared Modal/SGLang implementation. Imported by wrappers; not the normal deploy command. |
| `deploy_qwen3_next_endpoint.py` | Qwen3-Next baseline wrapper. |
| `deploy_qwen36_endpoint.py` | Qwen3.6 27B FP8 wrapper. |

## Model Profiles

| Model | Wrapper | Modal app | GPU | Deployment doc |
|---|---|---|---|---|
| Qwen3-Next 80B A3B | `infra/deploy_qwen3_next_endpoint.py` | `dynamic-unl-scoring` | H200 | [DeployQwen80B.md](../phase0/docs/DeployQwen80B.md) |
| Qwen3.6 27B FP8 | `infra/deploy_qwen36_endpoint.py` | `dynamic-unl-scoring-qwen36` | H100 | [DeployQwen36_27B.md](../phase0/docs/DeployQwen36_27B.md) |

## Modal CLI

Install and authenticate:

```bash
pipx install modal
modal setup
modal token info
```

Useful profile commands:

```bash
modal profile list
modal profile current
modal profile activate <name>
```

## Deploy

Qwen3-Next baseline:

```bash
modal run infra/deploy_qwen3_next_endpoint.py
modal deploy infra/deploy_qwen3_next_endpoint.py
```

Qwen3.6:

```bash
modal run infra/deploy_qwen36_endpoint.py
modal deploy infra/deploy_qwen36_endpoint.py
```

Endpoint URL formats:

```text
https://<workspace>--dynamic-unl-scoring-scoringendpoint-serve.modal.run
https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run
```

## New Model Wrapper

Add a new wrapper for each serious model candidate. The wrapper should set explicit `SCORING_*` defaults, then import `deploy_endpoint.py`. Do not deploy the shared implementation directly for normal model work.

The wrapper is the reviewable source for model ID, app name, volume, GPU, image tag, quantization, memory settings, and model-specific SGLang flags.

## Query And Score

Small query:

```bash
python scripts/query.py \
  --url https://<workspace>--<app-name>-scoringendpoint-serve.modal.run/v1 \
  --prompt "Hello"
```

Validator scoring:

```bash
python scripts/score_validators.py \
  --url https://<workspace>--<app-name>-scoringendpoint-serve.modal.run/v1 \
  --prompt-version v2
```

Model-specific capture commands live in the deployment docs linked above.

## Operations

```bash
modal app list
modal app logs <app-name>
modal app logs -f <app-name>
modal app dashboard <app-name>
modal app history <app-name>
modal app stop <app-name>
modal billing report
```

Volumes:

```bash
modal volume list
modal volume ls <volume-name>
modal volume delete <volume-name>
```

Known app and volume names:

| Model | App | Volume |
|---|---|---|
| Qwen3-Next 80B A3B | `dynamic-unl-scoring` | `scoring-model-weights` |
| Qwen3.6 27B FP8 | `dynamic-unl-scoring-qwen36` | `scoring-model-weights-qwen36` |

## Troubleshooting

| Symptom | Action |
|---|---|
| Permissions or billing error | Confirm Modal workspace billing and active profile. |
| Cold start is slow | Check logs; first image build includes model download and DeepGEMM precompile. |
| Corrupted or stale weights | Delete the model-specific volume, then redeploy that wrapper. |
| Runtime OOM | Check Modal logs and update the model-specific wrapper if the selected deployment profile changes. |
