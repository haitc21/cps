# Sprint 0 — Reproducible engineering foundation

**Dates:** 2026-07-17 to 2026-07-31
**Capacity:** focused foundation delivery
**Sprint Goal:** CPS installs from a pinned CPython 3.12 lockfile, starts with typed config and secret-safe logging, exposes live/ready health against PostgreSQL 18 and RabbitMQ, and passes CI quality gates without OpenStackSDK runtime dependencies.

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-001 | 5 | Agent | none | Done |
| CPS-002 | 5 | Agent | none | Done |
| CPS-003 | 3 | Agent | none | Done |
| CPS-004 | 5 | Agent | none | Done |

## Delivery tasks

- [x] Confirm contract/schema readiness (none required for Sprint 0 domain contracts).
- [x] Add failing acceptance/unit tests for each story.
- [x] Implement the smallest vertical slice per story.
- [x] Add integration coverage for PostgreSQL/RabbitMQ readiness.
- [x] Verify redaction, observability, and failure behavior.
- [x] Update operational documentation for local start/health.
- [x] Run the Definition of Done quality gates.
- [x] Harden worker lifecycle, logging service_name, read-only contract validation, integration opt-out, and cancellation shutdown path.

## Story details

### CPS-001 — Bootstrap a reproducible Python service

- **Depends on:** none
- **Acceptance:** clean checkout installs from lock; service starts; format/lint/type/unit commands pass; runtime reports Python 3.12; no OpenStackSDK dependency.
- **Verification:** `uv sync --frozen` (or equivalent), `pytest`, `ruff`, `mypy`, `python -c` version check, dependency graph scan.

### CPS-002 — Typed configuration and secret-safe logging

- **Depends on:** CPS-001
- **Acceptance:** missing required production config fails fast; password/token/authorization/`user_data` redact in tests; correlation ID accepted or generated and returned.
- **Verification:** unit tests for settings validation, redaction filter, correlation middleware.

### CPS-003 — Health and local infrastructure integration

- **Depends on:** CPS-001
- **Acceptance:** liveness is process-only; readiness is false when PostgreSQL or RabbitMQ is unavailable.
- **Verification:** unit tests with fakes; integration tests against Compose PostgreSQL/RabbitMQ.

### CPS-004 — Local quality pipeline

- **Depends on:** CPS-001..003
- **Acceptance:** Husky pre-commit runs formatting, lint, typing, default tests, contract validation, and secret scan. Infrastructure-backed integration and migration checks remain explicit developer/GitLab pipeline gates.
- **Verification:** Install hooks with `npm install`, then run `.husky/pre-commit` from a Git-compatible shell.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Local Python alias points to Store stub | Agent | Use `py -3.12` / explicit 3.12 interpreter | Mitigated |
| Sprint 1 migrations/contracts not present yet | Agent | Provide empty-safe migration/contract CI checks without domain scaffold | Mitigated |
| Compose services must remain running | Agent | Do not recreate volumes; use existing healthy stack | Mitigated |
| Windows Ctrl+C / task cancel skipped shutdown | Agent | `begin_shutdown()` in `finally` before closing RabbitMQ | Mitigated |

## Review evidence

- Demo scenario: start CPS API, call `/health/live` and `/health/ready` against local Compose; `cps worker` stays up and shuts down cleanly.
- Final DoD (2026-07-17, branch `sprint-0`):
  - `uv sync --frozen --all-extras` — ok
  - `ruff format --check`, `ruff check`, `mypy` — ok
  - `pytest -q` (default) — **22 passed, 1 skipped** (integration opt-out)
  - `CPS_RUN_INTEGRATION=1 pytest tests/integration` — **1 passed**
  - `alembic upgrade head` — ok (empty baseline)
  - `python -m cps.contracts.validate_contracts` — ok (0 fixtures; read-only)
  - `python -m detect_secrets scan --baseline .secrets.baseline ...` — ok
  - `docker build -t cps:sprint0 .` — ok
  - `git diff --check` — clean
  - Compose PostgreSQL/RabbitMQ remained healthy
- Hardening commits: `e928569` (worker/logging/contracts/integration defaults + cancellation path)
- Contract checksum: empty Sprint 0 manifest (`fixtures: {}`)
- Known limitations: no provider/domain APIs; Alembic empty baseline only.

## Retrospective actions

- Keep: TDD per story; Compose-backed readiness; cancel-safe worker `finally`.
- Improve: prefer `python -m detect_secrets`; integration tests opt-in locally.
- One measurable action for next sprint: land CPS-101 golden fixtures and checksums before any OPS pin copy.
