# Sprint 19 — CPS-1902 flavor lifecycle evidence

**Status:** CPS implementation/review complete; paired OPS-1902 live pending

## Canonical delivery

- Four explicit administrator operations cover flavor create, delete, project
  access, and extra-spec mutation. Core sizing fields remain immutable.
- Canonical request/result schema, five fixtures, message constants and
  manifest entries are versioned for the OPS pin.
- SYSTEM scope, exact capability, idempotency, case-insensitive uniqueness,
  ACTIVE/enabled freshness, project resolution and delete dependency checks
  fail before outbox publication.
- Typed result correlation validates operation type/state/provider identity
  before terminal transition or projection. Duplicate and late delivery remain
  idempotent and history-preserving.

## TDD and review evidence

- Initial RED: missing contract module and missing OpenAPI routes.
- Remediation cycle 1 closed discriminated schema, cross-operation key races,
  result binding, freshness and DB integration gaps.
- Cycle 2 aligned JSON Schema/runtime secret/provider/disjoint validation and
  expanded endpoint/reliability coverage.
- Cycle 3 added real ASGI authorization and real PostgreSQL inbox transaction
  coverage. Final reviewer decisions: `PASS1=PASS`, `PASS2=PASS`.
- Full suite: `960 passed, 202 skipped`.
- PostgreSQL 18 + RabbitMQ focused integration: `21 passed`.
- Contract validation: 26 files; Ruff/MyPy/Alembic/diff/secret gates passed.

## Pending paired acceptance

OPS-1902 must pin these canonical artifacts, execute replay-safe provider
handlers, and complete live CPS curl/OpenStack CLI create/access/spec/delete
comparison with zero residual resources. Credentials and raw provider bodies
are excluded from this runbook.
