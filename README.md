# Dynamic UNL Scoring

Scoring pipeline for PFT Ledger Dynamic UNL — AI-driven validator scoring using open-weight LLMs.

Currently in **Phase 0** (model selection benchmarking). This repo will evolve into the full scoring service described in Phase 1 of the [Design](https://github.com/postfiatorg/postfiatd/blob/main/docs/dynamic-unl/Design.md) and [Implementation Plan](https://github.com/postfiatorg/postfiatd/blob/main/docs/dynamic-unl/ImplementationPlan.md).

## Prerequisites

- Python 3.12+
- [OpenRouter](https://openrouter.ai) API key

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
```

## Running the Benchmark

Fetch real validator data from the VHS testnet API:

```bash
python scripts/fetch_vhs_data.py
```

Run the scoring prompt against candidate models (Qwen3-235B Thinking, Qwen3-235B Instruct, MiniMax M2.5):

```bash
python scripts/benchmark_models.py
```

Useful options:

```bash
# Run a single probe for one model without touching existing results
python scripts/benchmark_models.py --model qwen3-235b-thinking --runs 1

# Overwrite an existing run_N.json file
python scripts/benchmark_models.py --model minimax-m2.5 --runs 1 --force
```

Results are saved to `results/<model_name>/run_<N>.json`.

To avoid key-copy errors, the benchmark prompt gives each validator a short stable `validator_id` such as `v001`. The model scores those IDs, and the script remaps the saved `scores` output back to validator `master_key` values after parsing.

## Project Context

The Dynamic UNL system uses an open-weight LLM to score validators based on consensus performance, operational reliability, software diligence, geographic diversity, and identity/reputation. All validators must run the same model on the same GPU type (H200) to guarantee deterministic output for cross-validator verification.

Phase 0 selects the model. The constraint is fitting on a single H200 (141GB VRAM) at 4-bit quantization, which narrows the field to Qwen3-235B-A22B and MiniMax M2.5.
