# Sprint 1 — Contract and error semantics

**Dates:** 2026-07-31 to 2026-08-14
**Capacity:** 13 committed points in CPS; no stretch work begins before review
**Sprint Goal:** CPS publishes executable message/error contracts whose fixtures and JSON Schemas share one checksum manifest; OPS can pin them without drift.

## Committed stories — Must

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-101 — Canonical message envelope and schemas | 8 | Unassigned | OPS-101 | Ready |
| CPS-102 — Common error and API response model | 5 | Unassigned | OPS-103 | Ready |

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

- Test counts: fill only after commands run.
- Contract manifest SHA-256: fill only after CPS-102 refreshes the final manifest.
- Known limitations: no database domain, provider CRUD, RabbitMQ consumer, inventory, or OpenStack call.

## Implementation plan

Canonical: `docs/superpowers/plans/2026-07-17-sprint-1-contracts-operations-messaging.md`
