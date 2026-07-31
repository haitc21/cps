# CPS

Cloud Provider Management Service — provider-neutral control plane for OpenStack
provider onboarding, inventory, and VM operations via OPS.

## Requirements

- CPython 3.12 (do not use Python 3.14)
- [uv](https://github.com/astral-sh/uv) for locked installs
- Local infrastructure from `deploy/docker` (PostgreSQL 18, RabbitMQ 4.1)

## Setup

```bash
uv sync --all-extras --frozen
```

## Run

```bash
uv run cps serve --host 127.0.0.1 --port 8000
uv run cps worker --once
```

### Docker

Build and run the public API:

```bash
docker build -t cmp-cps .
docker run --rm --env-file .env -p 8000:8000 cmp-cps
```

Run the private CPS internal listener from the same image on port `8002`:

```bash
docker run --rm --env-file .env -p 8002:8002 cmp-cps \
  cps serve --internal --host 0.0.0.0 --port 8002
```

## Public API response envelope

All `/api/v1` admin and member endpoints return the CMP/BMS `BaseResponse`
shape:

```json
{
  "statusCode": 200,
  "message": "Success",
  "timestamp": "2026-07-31T08:00:00Z",
  "data": {}
}
```

Errors use the same envelope with `errorCode`, `path`, and structured `data`
(for example validation `fields`). Health (`/health/*`) and `/metrics` remain
unwrapped operational endpoints. Internal `/internal/v1/*` routes are unchanged.

### Pagination

List endpoints accept legacy `offset` (0-based) **or** canonical 1-based `page`,
but not both. Responses always emit BMS pagination metadata on `data`:

`items`, `page`, `limit`, `total`, `totalPages` with
`page = (offset // limit) + 1`. `offset` remains accepted for one release
cycle; new clients should send `page`.


```bash
uv sync --frozen --all-extras
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
uv run alembic upgrade head
uv run python -m cps.contracts.validate_contracts
```

Staged read-only secret verification runs via `bash .husky/pre-commit` (install
with `npm install`). Do not use `detect-secrets scan --baseline` as a
verification command.

Integration tests against Compose are opt-in:

```bash
CPS_RUN_INTEGRATION=1 uv run pytest -q
```

Windows (Python launcher): use `py -3.12 -m uv` instead of `uv`; set integration with `$env:CPS_RUN_INTEGRATION="1"`.

## Contract maintenance

After changing manifest-managed contract files:

```bash
uv run python -m cps.contracts.write_manifest
```

Commit the updated checksum manifest explicitly. This is not a verification gate.

GitLab CI will be added with the deployment pipeline.
