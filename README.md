# Dynamic UNL Scoring

Scoring pipeline for PFT Ledger Dynamic UNL — AI-driven validator scoring using open-weight LLMs.

**Phase 0 is complete.** Model selected, deployed on Modal with perfect determinism confirmed. See [docs/phase0/README.md](docs/phase0/README.md) for full details and [docs/CurrentRoadmap.md](docs/CurrentRoadmap.md) for what comes next.

## Prerequisites

- Python 3.12+
- [Modal](https://modal.com) account (for deployment)
- [OpenRouter](https://openrouter.ai) API key (for benchmarks only)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Deploy the Scoring Endpoint

```bash
modal deploy infra/deploy_endpoint.py
```

First deploy builds the image and pre-compiles DeepGEMM kernels (~18 min). Subsequent deploys take ~3 seconds.

## Score Validators

```bash
python scripts/score_validators.py --url <MODAL_ENDPOINT_URL>/v1
```

## Query the Endpoint

```bash
python scripts/query.py --url <MODAL_ENDPOINT_URL>/v1 --prompt "Hello"
```

## Fetch Validator Data

```bash
python scripts/fetch_vhs_data.py
```

## Run Benchmarks (Phase 0)

```bash
python benchmarks/round1.py --runs 1 --model qwen3-235b-thinking
python benchmarks/round2.py --runs 1 --model qwen3-next-80b-instruct
```

Benchmark results are in `benchmarks/results/`.

## Project Structure

```
├── scripts/           # Live utilities
│   ├── scoring_utils.py       # Shared scoring logic
│   ├── score_validators.py    # Production scoring runs
│   ├── query.py               # Generic endpoint client
│   └── fetch_vhs_data.py      # VHS testnet data fetcher
├── benchmarks/        # Phase 0 model selection (archival)
│   ├── round1.py              # Round 1 benchmark (235B models)
│   ├── round2.py              # Round 2 benchmark (80B models)
│   ├── test_runpod.py         # RunPod endpoint test
│   └── results/               # All benchmark results
├── infra/             # Deployment
│   └── deploy_endpoint.py     # Modal SGLang deployment
├── prompts/           # Scoring prompts
│   └── scoring_v1.txt
├── data/              # Validator snapshots
│   └── testnet_snapshot.json
├── results/           # Production scoring results
│   └── modal/
└── docs/              # Documentation
    ├── CurrentRoadmap.md
    └── phase0/
```
