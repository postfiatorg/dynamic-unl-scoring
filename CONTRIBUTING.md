# Contributing

Thanks for contributing to Dynamic UNL Scoring!

We welcome contributions from the community. Whether it's a bug fix, new feature, or documentation improvement, your help is greatly appreciated.

## Getting Started

### Prerequisites

- Python 3.12+ ([python.org](https://www.python.org) or [pyenv](https://github.com/pyenv/pyenv))
- Docker and Docker Compose

### Setup

1. Fork the repository at [github.com/postfiatorg/dynamic-unl-scoring](https://github.com/postfiatorg/dynamic-unl-scoring)
2. Clone your fork:

```bash
git clone git@github.com:YOUR_USERNAME/dynamic-unl-scoring.git
cd dynamic-unl-scoring
git remote add upstream git@github.com:postfiatorg/dynamic-unl-scoring.git
```

3. Install dependencies and configure environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

4. Start the scoring service with PostgreSQL:

```bash
docker compose up
```

5. Verify:

```bash
curl http://localhost:8001/health
```

### Working on a Feature or Fix

```bash
git fetch upstream main
git checkout -b your-branch-name upstream/main
```

When ready to submit, push your branch and open a pull request against `main`.

## Pull Request Requirements

Before submitting a PR:

- Run `pytest` and fix any failures
- Run `docker compose build` to confirm the Docker build succeeds
- Mark your PR as a [draft](https://github.blog/2019-02-14-introducing-draft-pull-requests/) until it's ready for review
- Fill in the PR template with a clear description of your changes
- Keep PRs focused — one feature or fix per PR

## Repository Layout

- `scoring_service/` — FastAPI scoring service (main application)
- `migrations/` — PostgreSQL schema migrations
- `tests/` — Test suite (pytest)
- `scripts/` — Standalone CLI tools (scoring, data fetching, ASN lookup)
- `infra/` — Modal LLM deployment
- `prompts/` — Scoring prompt templates
- `data/` — Validator snapshots and ASN data
- `phase0/` — Phase 0 archival (benchmarks, results, documentation)
- `docs/` — Active roadmap

## Code Style

- Follow existing patterns in the codebase
- Type hints for function signatures
- Pydantic models for structured data
