# Dynamic UNL Scoring

Scoring pipeline for PFT Ledger Dynamic UNL — AI-driven validator scoring using open-weight LLMs.

> Post Fiat context: Post Fiat is an XRP-derived network for capital markets and collective intelligence. It is currently live on public testnet, not production mainnet. Canonical project summary: https://postfiat.org/about/

This repository contains the validator-scoring and deterministic-replay work behind Post Fiat's published validator benchmark and validator-selection research.

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
pip install -r requirements.txt
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

## Dependencies

| File | Purpose | Used by |
|------|---------|---------|
| `requirements.txt` | All dependencies (service + scripts + tests) | Developers, CI |
| `requirements-docker.txt` | Service dependencies only | Dockerfile |

Developers always install `requirements.txt` — it has everything. `requirements-docker.txt` keeps the Docker image lean (no pyasn C extension, no pytest).

## Environments

The service supports multiple environments following the PostFiat branch-based deployment pattern:

| Environment | Branch | Docker Image Tag | Compose File | Env File |
|-------------|--------|-----------------|--------------|----------|
| Local dev | `main` | Built from source | `docker-compose.yml` | `.env` (from `.env.example`) |
| Devnet | `devnet` | `agtipft/dynamic-unl-scoring:devnet-latest` | `docker-compose.devnet.yml` | `.env.devnet` (reference) |
| Testnet | `testnet` | `agtipft/dynamic-unl-scoring:testnet-latest` | `docker-compose.testnet.yml` | `.env.testnet` (reference) |

### Local development

1. `cp .env.example .env` — fill in only what you need (most settings have defaults)
2. `docker compose up` — builds from source, starts PostgreSQL, mounts volumes for hot reloading
3. Your `.env` uses `localhost` for DATABASE_URL; docker-compose overrides it to `postgres` (the container hostname)

### Deployed environments (devnet/testnet)

Each Vultr instance requires a **one-time manual setup** before the first deployment (Docker, Caddy, firewall). See [docs/CurrentRoadmap.md](docs/CurrentRoadmap.md) Milestone 1.2 for the full setup commands. After that, all deployments are automated:

1. Push to `devnet` or `testnet` branch triggers the deploy workflow
2. Workflow builds Docker image, tags it (e.g., `devnet-latest`), pushes to Docker Hub
3. Workflow SSHs into the Vultr host and **generates `.env` from GitHub secrets** — this is how sensitive values (wallet keys, API keys, DB password) reach the server
4. Workflow copies the environment-specific compose file and runs `docker compose up`

The `.env.devnet` and `.env.testnet` files in the repo are **reference files** — they document the non-secret values for each environment but are not directly used at runtime. The deploy workflow bakes these values plus secrets into the generated `.env` on the server.

### GitHub secrets required for deployment

| Secret | Description | Per-environment |
|--------|-------------|-----------------|
| `DOCKERHUB_USERNAME` | Docker Hub login | Shared |
| `DOCKERHUB_TOKEN` | Docker Hub access token | Shared |
| `VULTR_SSH_USER` | SSH user for Vultr instances | Shared |
| `VULTR_SSH_KEY` | SSH private key | Shared |
| `VULTR_DEVNET_HOST` | Devnet Vultr instance IP | Devnet only |
| `VULTR_TESTNET_HOST` | Testnet Vultr instance IP | Testnet only |
| `DEVNET_DB_PASSWORD` / `TESTNET_DB_PASSWORD` | PostgreSQL password | Per-environment |
| `DEVNET_PFTL_WALLET_SECRET` / `TESTNET_PFTL_WALLET_SECRET` | Chain wallet secret | Per-environment |
| `DEVNET_PFTL_MEMO_DESTINATION` / `TESTNET_PFTL_MEMO_DESTINATION` | Memo destination address | Per-environment |
| `DEVNET_VL_PUBLISHER_TOKEN` / `TESTNET_VL_PUBLISHER_TOKEN` | VL signing token | Per-environment |
| `MODAL_ENDPOINT_URL` | Modal LLM endpoint | Shared |
| `MAXMIND_ACCOUNT_ID` | MaxMind account ID | Shared |
| `MAXMIND_LICENSE_KEY` | MaxMind license key | Shared |
| `IPFS_API_URL` | IPFS node API for uploading/pinning | Shared |
| `IPFS_API_USERNAME` | IPFS API basic auth username | Shared |
| `IPFS_API_PASSWORD` | IPFS API basic auth password | Shared |
| `IPFS_GATEWAY_URL` | IPFS public gateway for reading | Shared |

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
