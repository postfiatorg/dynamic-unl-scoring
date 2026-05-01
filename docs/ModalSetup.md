# Modal Setup

This guide explains how to deploy a standalone copy of the Dynamic UNL LLM
inference endpoint on Modal. It is intended for external operators who want to
run the same model and runtime configuration, send the same input, and compare
whether they receive the same deterministic output.

It assumes the operator is starting without a Modal account and does not already
know what Modal is. It does not require access to PostFiat deployment secrets,
validator infrastructure, the scoring-service database, IPFS, GitHub Pages, or
PFTL wallets.

## What Modal Provides

Modal is a serverless compute platform for running Python workloads on managed
cloud GPUs. This repository uses Modal to host the open-weight scoring model
behind an OpenAI-compatible HTTP API. External operators can deploy the same
endpoint and call it directly with `curl` or the helper scripts in this repo.

The shared deployment implementation is defined in `infra/deploy_endpoint.py`.
The active Qwen3.6 model is deployed through
`infra/deploy_qwen36_endpoint.py`, which supplies the model-specific defaults
before loading the shared Modal/SGLang implementation. The Qwen3-Next wrapper
remains in the repo only for historical baseline and fallback comparison.

## Current Dynamic UNL Inference Specs

Use these settings unless intentionally rotating the model or runtime:

| Item | Value |
|------|-------|
| Model ID | `Qwen/Qwen3.6-27B-FP8` |
| Short model name | `qwen36-27b-fp8` |
| Modal app name | `dynamic-unl-scoring-qwen36` |
| Endpoint class | `ScoringEndpoint` |
| GPU | `H100` |
| Tensor parallelism | `1` |
| SGLang image | `lmsysorg/sglang:nightly-dev-cu13-20260430-e60c60ef@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65` |
| Quantization | FP8 checkpoint, auto-detected by SGLang |
| Reasoning parser | `qwen3` |
| Determinism | `--enable-deterministic-inference` |
| Static memory fraction | `0.75` |
| Chunked prefill size | `4096` |
| Max running requests | `1` |
| FlashInfer workspace | `2147483648` bytes |
| Modal volume | `scoring-model-weights-qwen36` |
| Container timeout | `60` minutes |
| Scaledown window | `20` minutes |
| Web server startup timeout | `35` minutes |

These defaults live in `infra/deploy_qwen36_endpoint.py`. Do not change them for
normal reproducibility checks. They were chosen for the validated Qwen3.6 FP8
Modal/SGLang profile and keep full scoring-style prompts within predictable
memory headroom.

## Before You Start

You need:

1. A Modal account.
2. Billing enabled in Modal. The endpoint uses an H100 GPU, so the first deploy
   and any test requests can incur GPU charges.
3. A local checkout of this repository.
4. Python 3.12 or newer on your machine.
5. A prompt or request payload you want to compare across endpoints.

The Modal endpoint does not need PFTL wallet secrets, IPFS credentials, VL
publisher tokens, GitHub secrets, or database passwords.

## Create And Prepare A Modal Account

1. Go to `https://modal.com` and sign up.
2. Open the Modal dashboard.
3. Make sure billing is enabled for the workspace you will deploy into.
4. Use the personal workspace unless you specifically need an organization
   workspace.

If the workspace has multiple Modal environments, note which one should receive
the deployment. A single-environment workspace can usually use Modal's default
environment.

## Prepare Your Local Python Environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install modal
```

`requirements.txt` installs the helper-script dependencies used by this guide.
The Modal CLI is installed separately because it is only needed by operators who
deploy the GPU endpoint.

Verify that the CLI is available:

```bash
modal --help
```

## Authenticate The Modal CLI

Run:

```bash
modal setup
```

If your shell cannot find the `modal` executable, use:

```bash
python -m modal setup
```

Modal opens a browser-based authentication flow and writes local credentials for
the active profile. You can check the active token without printing the secret:

```bash
modal token info
modal config show
```

If you need to create a token from an authenticated web session instead, Modal
also supports:

```bash
modal token new
```

For a workspace with multiple environments, set or pass the intended Modal
environment before deployment:

```bash
modal config set-environment <environment-name>
```

or pass `--env <environment-name>` to the `modal run` and `modal deploy`
commands below.

## Optional Smoke Test Before Persistent Deployment

The local entrypoint in `infra/deploy_qwen36_endpoint.py` can create an ephemeral Modal
app, wait for SGLang to start, and send a small test prompt:

```bash
modal run infra/deploy_qwen36_endpoint.py
```

This consumes Modal GPU time. On success, the command prints an `Endpoint URL`,
a short response, elapsed time, and token counts. The URL from `modal run` is for
the ephemeral run, not the production deployment.

Use this step when validating a new Modal account, a new workspace, or a runtime
change. Skip it when you only need to redeploy the existing production-compatible
configuration.

## Deploy The Persistent Endpoint

Run this from the repository root:

```bash
modal deploy infra/deploy_qwen36_endpoint.py
```

If you need to target a specific Modal environment:

```bash
modal deploy --env <environment-name> infra/deploy_qwen36_endpoint.py
```

The first deployment does more work than later deployments:

1. Pulls the SGLang runtime image.
2. Installs `huggingface_hub[hf_transfer]`.
3. Uses `Qwen/Qwen3.6-27B-FP8` from the `scoring-model-weights-qwen36`
   Modal volume cache.
4. Pre-compiles DeepGEMM kernels on H100 during image build.
5. Creates a persistent Modal deployment named `dynamic-unl-scoring-qwen36`.

Expected timing from the current deployment script:

| Operation | Expected time |
|-----------|---------------|
| First deploy with image build and DeepGEMM compilation | about 18 minutes |
| Later deploys when the image and volume are cached | about 3 seconds |
| Cold start after the endpoint is idle | about 5 minutes |

Modal charges for GPU time while containers are active. The script keeps a warm
container for a 20-minute scaledown window after traffic so repeated scoring
requests do not pay the full cold-start cost each time.

## Find The Endpoint URL

Modal prints the web endpoint URL during deployment, and the same URL is visible
in the Modal dashboard for the deployed `dynamic-unl-scoring-qwen36` app.

The base URL usually looks like:

```text
https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run
```

The OpenAI-compatible API base is the same URL with `/v1` appended:

```text
https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run/v1
```

Use the actual URL printed by Modal or shown in the dashboard. The workspace and
environment slug are account-specific.

You can also open the app dashboard from the CLI:

```bash
modal app dashboard dynamic-unl-scoring-qwen36
```

## Validate The Endpoint

Set the API base URL for your shell. Include `/v1` for direct OpenAI-compatible
client calls and standalone helper scripts:

```bash
export MODAL_OPENAI_BASE_URL="https://<workspace>--dynamic-unl-scoring-qwen36-scoringendpoint-serve.modal.run/v1"
```

Send a small request:

```bash
curl "$MODAL_OPENAI_BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.6-27B-FP8",
    "messages": [
      {
        "role": "user",
        "content": "Reply with the words Dynamic UNL endpoint ready."
      }
    ],
    "chat_template_kwargs": {"enable_thinking": false},
    "temperature": 0,
    "max_tokens": 32
  }'
```

The first request after idle can take several minutes because the H100 container
must start, load weights, and capture CUDA graphs. Warm requests should be much
faster.

You can also use the helper script:

```bash
python scripts/query.py \
  --url "$MODAL_OPENAI_BASE_URL" \
  --disable-thinking \
  --prompt "Reply with the words Dynamic UNL endpoint ready." \
  --max-tokens 32
```

For scoring-prompt validation against the repository's local benchmark data:

```bash
python scripts/score_validators.py \
  --url "$MODAL_OPENAI_BASE_URL" \
  --prompt-version v2 \
  --disable-thinking \
  --runs 1 \
  --session-name modal-setup-check
```

`scripts/score_validators.py` writes results under `phase0/results/modal/`. Do not run
large repeated benchmark sessions unless you intend to spend the GPU time.

## Run A Determinism Check

For deterministic comparisons, keep the request parameters identical:

```text
model: Qwen/Qwen3.6-27B-FP8
temperature: 0
max_tokens: same value for every run
messages: byte-for-byte same message content and order
chat_template_kwargs.enable_thinking: false
```

Run the same request several times against your endpoint:

```bash
for i in 1 2 3; do
  python scripts/query.py \
    --url "$MODAL_OPENAI_BASE_URL" \
    --disable-thinking \
    --prompt "Reply with the words Dynamic UNL endpoint ready." \
    --max-tokens 32
done
```

For a stronger check using the repository's validator-scoring prompt and local
snapshot data:

```bash
python scripts/score_validators.py \
  --url "$MODAL_OPENAI_BASE_URL" \
  --prompt-version v2 \
  --disable-thinking \
  --runs 5 \
  --session-name reproducibility-check
```

This writes one JSON result per run under `phase0/results/modal/`. Compare the
response content, scores, token counts, and finish reason across runs. The
Phase 0 Modal validation in this repo produced bit-identical output across
repeated full scoring-prompt runs with this runtime configuration.

If you compare your endpoint against another operator's endpoint, both operators
must use the same repository revision or otherwise confirm that
`infra/deploy_endpoint.py`, the relevant model wrapper, `prompts/scoring_v2.txt`,
input snapshots, and request parameters match.

Do not put wallet secrets, IPFS credentials, GitHub PATs, or database passwords
inside Modal for this endpoint. Reproducibility checks only need the model
endpoint and the input you are testing.

## What The Deployment Script Does

`infra/deploy_endpoint.py` is the shared runtime implementation. The Qwen3.6
wrapper provides the active model defaults:

1. Defines `modal.App(name="dynamic-unl-scoring-qwen36")`.
2. Builds from the pinned SGLang nightly image in `infra/deploy_qwen36_endpoint.py`.
3. Installs Hugging Face transfer support.
4. Sets `SGLANG_FLASHINFER_WORKSPACE_SIZE=2147483648`.
5. Uses the `scoring-model-weights-qwen36` Modal volume for the Hugging Face cache.
6. Serves `Qwen/Qwen3.6-27B-FP8` from that volume-backed cache.
7. Runs `sglang.compile_deep_gemm` on H100 during image build.
8. Starts `python -m sglang.launch_server` with the selected model.
9. Enables deterministic inference, SGLang metrics, and the `qwen3` reasoning parser.
10. Exposes the SGLang HTTP server on port `8000` through `@modal.web_server`.

The SGLang server already exposes OpenAI-compatible paths under `/v1`, including
`/v1/chat/completions`. The helper scripts use the OpenAI Python client with
`api_key="not-needed"` because this Modal web endpoint is not protected by an
application-level API key.

## Safe Operations

- Redeploy with `modal deploy infra/deploy_qwen36_endpoint.py` after changing
  `infra/deploy_endpoint.py` or `infra/deploy_qwen36_endpoint.py`.
- Check recent logs with `modal app logs dynamic-unl-scoring-qwen36`.
- Follow logs during a cold start with `modal app logs -f dynamic-unl-scoring-qwen36`.
- Open the dashboard with `modal app dashboard dynamic-unl-scoring-qwen36`.
- Stop the deployed app only when you intentionally want the endpoint offline:
  `modal app stop dynamic-unl-scoring-qwen36`.

Stopping the app makes your copied endpoint unavailable until you deploy it
again.

## Common Problems

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `modal: command not found` | Modal CLI is not installed in the active shell | Activate `.venv` and run `python -m pip install modal` |
| Authentication prompt repeats | CLI profile is not set or token is invalid | Run `modal setup`, then `modal token info` |
| Deploy asks for an environment | Workspace has multiple Modal environments | Run `modal config set-environment <name>` or pass `--env <name>` |
| First deploy takes a long time | Image build, model download, and DeepGEMM pre-compilation are running | Wait for the build to finish; later deploys reuse cached work |
| First request appears stuck | Cold start is loading the model and capturing CUDA graphs | Wait several minutes; the endpoint has a 35-minute startup timeout |
| Large prompt fails or the server restarts | Runtime memory settings were changed | Restore the default memory, prefill, FlashInfer, and request-limit settings |
| Helper script cannot connect | URL is missing `/v1` | Pass the OpenAI-compatible base URL ending in `/v1` |

## References

- `infra/deploy_endpoint.py` - shared deployment implementation.
- `infra/deploy_qwen36_endpoint.py` - active model runtime settings.
- `infra/deploy_qwen3_next_endpoint.py` - historical Qwen3-Next baseline settings.
- `phase0/docs/DeployQwen36_27B.md` - active Qwen3.6 deployment profile and validation.
- `scripts/query.py` - small direct endpoint query.
- `scripts/score_validators.py` - scoring prompt validation against local data.
- `phase0/docs/DeployQwen80B.md` - deployment tuning rationale and determinism
  results for the historical Qwen3-Next baseline.
- Modal official docs:
  - `https://modal.com/docs/guide`
  - `https://modal.com/docs/reference/cli/deploy`
  - `https://modal.com/docs/guide/webhooks`
  - `https://modal.com/docs/guide/webhook-urls`
