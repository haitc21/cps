# CPS

Cloud Provider Management Service — provider-neutral control plane for OpenStack
provider connections, credentials, inventory, and VM operations via OPS.

## Requirements

- CPython 3.12 (do not use Python 3.14)
- [uv](https://github.com/astral-sh/uv) for locked installs
- Local infrastructure from `deploy/docker` (PostgreSQL 18, RabbitMQ 4.1)

## Setup

```powershell
py -3.12 -m uv sync --all-extras --frozen
```

## Run

```powershell
py -3.12 -m uv run cps serve --host 127.0.0.1 --port 8000
py -3.12 -m uv run cps worker --once
```

## Quality gates

```powershell
py -3.12 -m uv sync --frozen --all-extras
py -3.12 -m uv run ruff format --check src tests
py -3.12 -m uv run ruff check src tests
py -3.12 -m uv run mypy
py -3.12 -m uv run pytest -q
py -3.12 -m uv run alembic upgrade head
py -3.12 -m uv run python -m cps.contracts.validate_contracts
py -3.12 -m uv run python -m cps.contracts.write_manifest
py -3.12 -m uv run python -m detect_secrets scan --baseline .secrets.baseline --exclude-files "(?i)(.*\.venv/.*|.*uv\.lock$|.*\.git/.*|(.*/)?checksums\.json$)"
```
Integration tests against Compose are opt-in:

```powershell
$env:CPS_RUN_INTEGRATION="1"
py -3.12 -m uv run pytest -q
```

Local pre-commit quality gate: `.husky/pre-commit` (install with `npm install`). GitLab CI will be added with the deployment pipeline.
