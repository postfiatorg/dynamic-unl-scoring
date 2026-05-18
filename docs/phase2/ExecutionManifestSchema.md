# Execution Manifest Schema

This document defines the intended structure and purpose of
`runtime/execution_manifest.json` for verifier-ready scoring artifact bundles.

The execution manifest is the round's execution contract. It answers one
question:

```text
What exact setup was used to produce this round, and what must another operator
match to verify it?
```

This is a schema and design document only. It does not change artifact
publishing, model scoring, sidecar behavior, Validator List signing, or
historical artifacts.

## Why This Exists

The current `scoring_config.json` is useful for humans, but it is too small for
machine verification. It records fields such as model name, prompt version,
temperature, and max tokens. A validator sidecar needs more exact information:

- Which exact model repository and revision to load.
- Which runtime image and launch arguments to use.
- Which request settings were sent to the model.
- Which prompt, parser, selector, and VL generator code produced the outputs.
- Which canonical JSON rule is used when comparing hashes.
- Whether model inference happened at all.

The execution manifest should be minimal, but it must remove uncertainty. If a
field does not help another operator run the same setup or interpret the same
outputs, it should not be in this file.

## Relationship To Other Bundle Files

The manifest is not the index for the whole bundle and it is not the place for
all output hashes.

```text
bundle.json
  Lists bundle entrypoints and file hashes.

runtime/execution_manifest.json
  Defines the execution setup for this round.

outputs/verification_hashes.json
  Stores the hashes a verifier compares after running or inspecting the round.
```

That separation keeps the execution manifest focused:

```text
bundle.json says: "Here are the files."
execution_manifest.json says: "Here is how execution worked."
verification_hashes.json says: "Here are the expected comparison hashes."
```

## Required Normal-Round Manifest

A normal scoring round performs model inference. Its manifest must include only
the fields needed to reproduce or verify that execution.

```json
{
  "schema_version": 1,
  "round": {
    "kind": "normal",
    "network": "testnet",
    "round_number": 241,
    "published_at": "2026-05-18T00:00:00+00:00",
    "inference_performed": true
  },
  "model": {
    "provider": "huggingface",
    "repo_id": "Qwen/Qwen3.6-27B-FP8",
    "revision": "<full Hugging Face commit hash>",
    "served_name": "Qwen/Qwen3.6-27B-FP8"
  },
  "runtime": {
    "kind": "modal_sglang",
    "image": "lmsysorg/sglang:nightly-dev-cu13-20260430-e60c60ef@sha256:5d9ec71597ade6b8237d61ae6f01b976cb3d5ad2c1e3cf4e0acaf27a9ff49a65",
    "gpu": "H100",
    "tensor_parallelism": 1,
    "launch_command": [
      "python",
      "-m",
      "sglang.launch_server"
    ],
    "launch_args": [
      "--model-path",
      "Qwen/Qwen3.6-27B-FP8",
      "--served-model-name",
      "Qwen/Qwen3.6-27B-FP8",
      "--tp",
      "1",
      "--mem-fraction-static",
      "0.75",
      "--chunked-prefill-size",
      "4096",
      "--max-running-requests",
      "1",
      "--enable-deterministic-inference",
      "--enable-metrics",
      "--trust-remote-code",
      "--reasoning-parser",
      "qwen3"
    ],
    "environment": {
      "SGLANG_FLASHINFER_WORKSPACE_SIZE": "2147483648"
    }
  },
  "request": {
    "type": "openai_chat_completions",
    "file": "inputs/model_request.json",
    "method": "chat.completions.create",
    "model": "Qwen/Qwen3.6-27B-FP8",
    "temperature": 0,
    "max_tokens": 16384,
    "response_format": {
      "type": "json_object"
    },
    "extra_body": {
      "chat_template_kwargs": {
        "enable_thinking": false
      }
    },
    "timeout_seconds": 2100
  },
  "code": {
    "repository": "postfiatorg/dynamic-unl-scoring",
    "commit": "<git commit that produced the round>",
    "prompt": {
      "version": "v5",
      "template_path": "prompts/scoring_v5.txt",
      "template_sha256": "<sha256 of prompt template>"
    },
    "parser": {
      "module": "scoring_service.services.response_parser",
      "version": "git:<commit>"
    },
    "selector": {
      "module": "scoring_service.services.unl_selector",
      "version": "git:<commit>",
      "parameters": {
        "score_cutoff": 40,
        "max_size": 35,
        "min_score_gap": 5
      }
    },
    "vl_generator": {
      "module": "scoring_service.services.vl_generator",
      "version": "git:<commit>"
    }
  },
  "canonicalization": {
    "hash_algorithm": "sha256",
    "text_encoding": "utf-8",
    "json_encoding": {
      "sort_keys": true,
      "separators": [
        ",",
        ":"
      ],
      "default": "str"
    }
  }
}
```

## Required Override Manifest

An override round does not perform model inference. The manifest must make that
obvious so a verifier does not try to run a model.

```json
{
  "schema_version": 1,
  "round": {
    "kind": "override",
    "network": "testnet",
    "round_number": 242,
    "published_at": "2026-05-18T00:00:00+00:00",
    "inference_performed": false
  },
  "override": {
    "type": "custom",
    "reason": "Operator-supplied reason"
  },
  "code": {
    "repository": "postfiatorg/dynamic-unl-scoring",
    "commit": "<git commit that produced the round>",
    "vl_generator": {
      "module": "scoring_service.services.vl_generator",
      "version": "git:<commit>"
    }
  },
  "canonicalization": {
    "hash_algorithm": "sha256",
    "text_encoding": "utf-8",
    "json_encoding": {
      "sort_keys": true,
      "separators": [
        ",",
        ":"
      ],
      "default": "str"
    }
  }
}
```

Override manifests must not include `model`, `runtime`, or `request` sections.
Those sections would imply that inference happened.

## Dry-Run Notes

Dry-runs use the same execution shape as normal rounds because inference does
happen. The important differences are:

- `round.kind` is `dry_run`.
- `round.dry_run_id` is required.
- `round.round_number` is omitted or null.
- No signed Validator List is produced.
- The bundle remains private and is not a public verification target.

Dry-runs are useful for testing manifest generation before changing public
artifact publication.

## Field Explanations

Every field in the manifest should earn its place.

| Field | Why it is necessary |
|---|---|
| `schema_version` | Lets future readers know which manifest format they are reading |
| `round.kind` | Tells a verifier whether this is normal inference, private dry-run, or no-inference override |
| `round.network` | Prevents mixing devnet, testnet, or future mainnet artifacts |
| `round.round_number` | Binds the manifest to the public scoring round |
| `round.published_at` | Records when this execution package was produced |
| `round.inference_performed` | Prevents a verifier from running the model for override rounds |
| `model.provider` | Tells a verifier where model identity is defined |
| `model.repo_id` | Names the Hugging Face model repository |
| `model.revision` | Pins the exact Hugging Face repository snapshot |
| `model.served_name` | Matches the OpenAI-compatible `model` value expected by the runtime |
| `runtime.kind` | Identifies the runtime family, such as Modal plus SGLang |
| `runtime.image` | Pins the container image and digest used for inference |
| `runtime.gpu` | Identifies the GPU class expected for reproducibility |
| `runtime.tensor_parallelism` | Captures the model parallelism setting used by SGLang |
| `runtime.launch_command` | Names the command used to start the runtime |
| `runtime.launch_args` | Captures runtime flags that can affect output or feasibility |
| `runtime.environment` | Captures non-secret environment values that affect runtime behavior |
| `request.file` | Points to the exact request messages in the bundle |
| `request.method` | Identifies the OpenAI-compatible API method |
| `request.model` | Captures the model string sent in the request |
| `request.temperature` | Must be deterministic, currently `0` |
| `request.max_tokens` | Affects response length and must match |
| `request.response_format` | Forces JSON output expectations |
| `request.extra_body` | Captures Qwen no-thinking settings |
| `request.timeout_seconds` | Records the client timeout used for the scoring call |
| `code.repository` | Identifies the source repository for prompt, parser, selector, and VL generator |
| `code.commit` | Pins the code version used for this execution |
| `code.prompt` | Identifies the prompt template that produced `inputs/model_request.json` |
| `code.parser` | Identifies the code that turned raw model text into scores |
| `code.selector` | Identifies the code and parameters that turned scores into the selected UNL |
| `code.vl_generator` | Identifies the code path that produced the signed Validator List |
| `canonicalization` | Defines how JSON is converted to bytes before hashing |

## Model Identity

The required model identity is:

```text
provider + repo_id + full revision commit hash
```

For the current model, that means:

```text
provider: huggingface
repo_id: Qwen/Qwen3.6-27B-FP8
revision: <full Hugging Face commit hash>
```

Do not use a moving branch name such as `main` as the manifest revision. A full
commit hash is required because it points to one exact repository snapshot.

The Hugging Face Hub supports downloading a file or an entire repository at a
specific revision, including a full commit hash. For model repositories with
large files, the commit pins the file pointers used by the snapshot. That is
the necessary baseline for telling validators what to run.

If we later want byte-level verification independent of the Hugging Face cache
or mirror being used, add a separate model snapshot manifest with file paths,
sizes, and SHA-256 hashes for the downloaded model files. Do not put a giant
weight-file hash list directly into every round manifest unless it is truly
needed per round.

## Optional Runtime Details

Some runtime details are useful but should not be part of the minimal required
manifest until the service can collect them reliably.

Examples:

- CUDA driver version.
- CUDA runtime version.
- Python version.
- SGLang package version.
- Exact downloaded model file hashes.

These can be added later in one of two ways:

1. As optional fields in a future manifest version.
2. As a separate runtime or model snapshot manifest referenced by this file.

The rule is: do not publish placeholders as if they are facts. If a value is not
known, leave it out until it can be collected reliably.

## Canonical JSON Rule

The current codebase hashes structured JSON using this practical rule:

```text
json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
sha256(utf8_bytes)
```

That rule is not full RFC 8785 JSON Canonicalization Scheme. The important
thing is consistency: every component that compares hashes must use the same
rule.

If the project later moves to a stricter canonicalization standard, increment
`schema_version` and make the change explicit.

## What Should Not Be In The Manifest

Do not include:

- Modal proxy auth secrets.
- Wallet seeds or private keys.
- GitHub tokens, IPFS credentials, database URLs, or RPC credentials.
- The final root IPFS CID, because the root CID depends on bundle content.
- GitHub Pages commit URL or on-chain memo transaction hash, because those are
  known only after the bundle is created.
- Output comparison hashes, because those belong in
  `outputs/verification_hashes.json`.
- A self-declared "ready" flag. Readiness should be determined by validators
  checking whether all required fields are present and valid.

## Relationship To `verification_hashes.json`

The execution manifest defines how execution worked.

`outputs/verification_hashes.json` stores what a verifier compares.

Keep those responsibilities separate. The manifest should not duplicate the
same hashes that already live in `outputs/verification_hashes.json`. A verifier
should use `bundle.json` to find the hash file and use the manifest to understand
how those hashes were produced.

## Implementation Sources

Use these current sources when implementing manifest generation:

| Manifest field | Current source |
|---|---|
| `round.round_number` | Orchestrator round number |
| `round.network` | `ScoringSnapshot.network` |
| `round.published_at` | Artifact publication timestamp |
| `round.kind` | Publish path: normal, dry-run, or override |
| `round.inference_performed` | Publish path |
| `model.repo_id` | `settings.scoring_model_id` |
| `model.served_name` | `settings.scoring_model_id` |
| `model.revision` | New deployment/runtime value required |
| `runtime.image` | `infra/deploy_qwen36_endpoint.py` |
| `runtime.gpu` | `infra/deploy_qwen36_endpoint.py` |
| `runtime.launch_args` | `infra/deploy_endpoint.py` |
| `request.temperature` | `settings.scoring_temperature` |
| `request.max_tokens` | `settings.scoring_max_tokens` |
| `request.timeout_seconds` | `settings.modal_request_timeout_seconds` |
| `request.extra_body` | `QWEN_NON_THINKING_EXTRA_BODY` when thinking is disabled |
| `code.commit` | New deployment/runtime value required |
| Prompt version | `PROMPT_VERSION` in `ipfs_publisher.py` |
| Prompt template path | `PromptBuilder.PROMPT_PATH` |
| Prompt template hash | New helper required |
| Selector parameters | `settings.unl_score_cutoff`, `settings.unl_max_size`, `settings.unl_min_score_gap` |
| Override type/reason | Admin override publish arguments |

## Validation Rules

Future tests should reject malformed manifests.

Minimum validation rules:

- `schema_version` must be `1`.
- `round.kind` must be one of `normal`, `dry_run`, or `override`.
- `round.inference_performed` must be `false` for override rounds.
- Normal and dry-run manifests must include `model`, `runtime`, and `request`.
- Override manifests must not include `model`, `runtime`, or `request`.
- `model.revision` must be a full Hugging Face commit hash, not a branch name.
- `runtime.image` must include an immutable digest.
- `code.commit` must be present.
- No secrets may appear anywhere in the manifest.
- Every file path referenced by the manifest must exist in the bundle.

## Out Of Scope

This document does not implement:

- Artifact publishing changes.
- Staged bundle file names.
- Sidecar verification.
- Commit-reveal memos.
- Model inference changes.
- Validator List signing changes.
- Backfilling old immutable artifacts.

This document is the blueprint. The implementation work should turn this schema
into `runtime/execution_manifest.json` files published by the scoring service.

## Decision Summary

Recommended direction:

- Keep `runtime/execution_manifest.json` focused on execution setup only.
- Require a full Hugging Face commit hash for model identity.
- Require an immutable runtime image digest and launch arguments.
- Require the exact request contract.
- Require code commit, prompt hash, parser identity, selector parameters, and
  VL generator identity.
- Keep output hashes in `outputs/verification_hashes.json`.
- Do not include a self-declared readiness flag.
- Add model file hashes later only if we need byte-level verification beyond the
  pinned Hugging Face revision.

The practical outcome is that a future developer can read this document and
understand exactly what the execution manifest is trying to say: "This is the
setup that produced the round, and this is what another operator must match to
verify it."
