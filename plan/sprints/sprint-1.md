# Sprint 1 — Contract and error semantics

**Dates:** 2026-07-31 to 2026-08-14
**Capacity:** 13 committed points in CPS; no stretch work begins before review
**Sprint Goal:** CPS publishes executable message/error contracts whose fixtures and JSON Schemas share one checksum manifest; OPS can pin them without drift.

## Committed stories — Must

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-101 — Canonical message envelope and schemas | 8 | Unassigned | OPS-101 | Done |
| CPS-102 — Common error and API response model | 5 | Unassigned | OPS-103 | Done |

**Total:** 13 points.

## Deferred to Sprint 1B

- CPS-103 — Initial database migration and unit of work.
- CPS-104 — Operation state machine and immutable history.
- CPS-105 — Idempotent operation creation.
- CPS-106 — Transactional outbox publisher and inbox consumer.

These stories retain their product-backlog priority and points. They require a separate reviewed implementation plan and are not part of Sprint 1 exit criteria.

## Delivery order

1. Extend manifest validation to cover fixtures and JSON Schemas.
2. CPS-101 creates canonical envelope, schemas, and five golden fixtures.
3. OPS-101 pins the completed CPS manifest and files.
4. CPS-102 adds the common error model and all required HTTP mappings.
5. OPS-103 consumes the pinned error contract for SDK normalization and retry classification.

## Definition of Done

- Every golden fixture validates through Pydantic and Draft 2020-12 JSON Schema.
- Unknown major schema versions reject; additive fields remain compatible.
- Command fixture contains only a credential reference; event/inventory fixtures omit it.
- Manifest detects changes under both `fixtures/` and `jsonschema/`.
- Error mappings cover validation, not-found, conflict, capability, provider, timeout, and internal failures.
- CPS has no OpenStackSDK dependency and no Sprint 1B database/messaging scaffold.
- Ruff, mypy, pytest, contracts, secret scan, Docker build, and `git diff --check` pass.

## Risks

| Risk | Mitigation |
|---|---|
| CPS/OPS drift | OPS stores canonical manifest snapshot and validates every pinned file in CI. |
| Secret leakage in fixtures/errors | Explicit forbidden-key tests plus detect-secrets. |
| Scope creep into persistence/messaging | CPS-103..106 remain deferred and absent from this plan. |

## Review evidence

- Verification date: **2026-07-20** (Sprint 1A Task 5, branch `main`, HEAD `ba564e5`).
- Story commits:
  - CPS-101 — `ba564e5` (`feat: initialize CPS service`; envelope, fixtures, JSON Schemas delivered in same commit)
  - CPS-102 — `ba564e5` (common error contract, API handlers, error fixture/schema in same commit)
- Final DoD gates (fresh run, exit 0 unless noted):
  - `py -3.12 -m uv lock --check` — ok
  - `py -3.12 -m uv sync --frozen --all-extras` — ok
  - `py -3.12 -m uv run ruff format --check src tests` — ok
  - `py -3.12 -m uv run ruff check src tests` — ok
  - `py -3.12 -m uv run mypy` — ok (31 source files)
  - `py -3.12 -m uv run pytest -q` — **76 passed, 5 skipped**
  - `py -3.12 -m uv run python -m cps.contracts.validate_contracts` — ok (**8 manifest-managed contract files**)
  - read-only secret verification — ok (`detect-secrets-hook --baseline .secrets.baseline` per tracked file from `git ls-files -z`, repo exclude regex, NUL-safe argv; **81 files scanned**; baseline SHA unchanged `d44dc71f8b1ce2d873ce45d7a13781e0a361b68979a137a8d37a06e031e81bde`)
  - `git diff --check` — ok
  - `docker build -t cps:sprint1a .` — ok
  - host `.husky/pre-commit` — **exit 0**
- Contract manifest SHA-256 (`src/cps/contracts/checksums.json`): `79f4d97a07e53357210ede4f905c65d905776aa12952e06280b5ad7d6532bc43` (959 bytes).
- Alembic: empty Sprint 0 baseline only; `alembic current` exits 0 — no Sprint 1B domain migrations applied.
- Warnings: 1 pre-existing `StarletteDeprecationWarning` (httpx vs httpx2 in FastAPI testclient).
- Known limitations:
  - No provider connection CRUD, credential storage domain, or CPS → OPS runtime integration in Sprint 1A.
  - No outbox/inbox, RabbitMQ consumer, or operation persistence (deferred CPS-103..106).
  - No OpenStack calls from CPS (by design).
  - Alembic/SQLAlchemy present from Sprint 0 scaffold only; Sprint 1A adds contracts/errors only.

## Sprint Review

- CPS-101 delivered canonical `MessageEnvelope`, five golden fixtures, exported JSON Schema, and manifest coverage for fixtures and schemas.
- CPS-102 delivered `CommonError`, domain error types, FastAPI handlers for validation/not-found/conflict/capability/provider/timeout/internal paths, and error fixture/schema in the manifest.
- OPS-101 and OPS-103 completed in sibling OPS repo; cross-repo byte parity of manifest verified during Task 5.
- All Sprint 1A committed stories meet Definition of Done with fresh gate evidence.

## Sprint Retrospective

- Keep: contract-first TDD; checksum manifest over fixtures and jsonschema; forbidden-key fixture tests; Husky as local quality gate.
- Improve: split story commits per canonical plan boundary when history allows (CPS-101/102 landed in one initialize commit); use read-only `detect-secrets-hook` full-tracked verification (not `scan --baseline`) for evidence gates.
- Sprint 1B handoff: produce a separate reviewed plan for CPS-103..106 before any database/messaging scaffold; OPS-102/104 remain whole (topology + dispatch together).

## Sprint 1B

Sprint 1A is closed. Sprint 1B backlog and delivery order: `plan/sprints/sprint-1b.md`.

Executable implementation plan (review before code):

- Canonical: `docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`

## Implementation plan (Sprint 1A)

Canonical: `docs/superpowers/plans/2026-07-17-sprint-1-contracts-operations-messaging.md`
