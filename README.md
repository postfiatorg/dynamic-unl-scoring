# Dynamic UNL Scoring

Scoring pipeline for PFT Ledger Dynamic UNL — AI-driven validator scoring using open-weight LLMs.

**Phase 1 in progress.** Building the foundation scoring service. See [docs/phase0/README.md](docs/phase0/README.md) for Phase 0 results and [docs/CurrentRoadmap.md](docs/CurrentRoadmap.md) for the full roadmap.

## Prerequisites

- Python 3.12+
- Docker and Docker Compose (for the scoring service)
- [Modal](https://modal.com) account (for LLM inference endpoint)

## Development Setup

```bash
# Clone and set up Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

# Start the scoring service with PostgreSQL
docker compose up

# Verify
curl http://localhost:8001/health
```

The service runs on port 8001 (mapped to container port 8000).

## Running Tests

```bash
pytest
```

## Deploy the LLM Endpoint

```bash
modal deploy infra/deploy_endpoint.py
```

First deploy builds the image and pre-compiles DeepGEMM kernels (~18 min). Subsequent deploys take ~3 seconds.

## Standalone Scripts

These scripts run independently of the service, directly against the Modal endpoint or VHS API.

```bash
# Score validators against the Modal endpoint
python scripts/score_validators.py --url <MODAL_ENDPOINT_URL>/v1

# Query the endpoint
python scripts/query.py --url <MODAL_ENDPOINT_URL>/v1 --prompt "Hello"

# Fetch validator data from VHS
python scripts/fetch_vhs_data.py

# ASN lookup for a single IP
python scripts/lookup_asn.py --ip 144.202.24.188

# ASN lookup for all topology nodes
python scripts/lookup_asn.py --save
```

## Benchmarks (Phase 0)

```bash
python benchmarks/round1.py --runs 1 --model qwen3-235b-thinking
python benchmarks/round2.py --runs 1 --model qwen3-next-80b-instruct
```

Results are in `benchmarks/results/`.

## Project Structure

```
├── scoring_service/   # FastAPI scoring service (Phase 1)
│   ├── main.py               # Application entry point
│   ├── config.py             # Environment settings
│   ├── database.py           # PostgreSQL connection + migrations
│   ├── logging.py            # Structured logging (structlog)
│   ├── api/                  # HTTP endpoints
│   ├── services/             # Business logic (M1.2+)
│   └── models/               # Data models (M1.2+)
├── migrations/        # PostgreSQL schema migrations
├── tests/             # Test suite
├── scripts/           # Standalone CLI tools
│   ├── scoring_utils.py      # Shared scoring logic
│   ├── score_validators.py   # Production scoring runs
│   ├── query.py              # Generic endpoint client
│   ├── fetch_vhs_data.py     # VHS testnet data fetcher
│   └── lookup_asn.py         # ASN/ISP lookup
├── benchmarks/        # Phase 0 model selection (archival)
├── infra/             # Modal LLM deployment
├── prompts/           # Scoring prompt templates
├── data/              # Validator snapshots + ASN data
├── results/           # Production scoring results
└── docs/              # Roadmap + Phase 0 documentation
```
