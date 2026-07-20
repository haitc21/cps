# CPS Product Backlog

Priorities use Must/Should/Could. Sprint allocation is the initial forecast and may change during refinement without changing dependencies or acceptance criteria.

## Epic CPS-E0 — Engineering foundation

### CPS-001 — Bootstrap a reproducible Python service

- **Sprint/Priority/Points:** 0 / Must / 5
- **Depends on:** none
- **Outcome:** developers and CI run the same CPython 3.12 dependency graph.
- **Tasks:** create `pyproject.toml`, src layout, lockfile, application factory, CLI/entrypoint, formatting/lint/type/test configuration, and Python 3.12 runtime Dockerfile.
- **Acceptance:** clean checkout installs from lock; service starts; format/lint/type/unit commands pass; runtime reports Python 3.12; CPS has no OpenStackSDK dependency.

### CPS-002 — Typed configuration and secret-safe logging

- **Sprint/Priority/Points:** 0 / Must / 5
- **Depends on:** CPS-001
- **Tasks:** Pydantic settings, environment profiles, structured logging, correlation middleware, redaction filters, startup validation.
- **Acceptance:** missing required production config fails fast; password/token/authorization/`user_data` fields redact in tests; correlation ID is accepted or generated and returned.

### CPS-003 — Health and local infrastructure integration

- **Sprint/Priority/Points:** 0 / Must / 3
- **Depends on:** CPS-001
- **Tasks:** live/ready endpoints, PostgreSQL 18 and RabbitMQ checks, Compose documentation alignment.
- **Acceptance:** liveness is process-only; readiness becomes false when DB or RabbitMQ is unavailable; Valkey is not a CPS readiness dependency.

### CPS-004 — Local quality pipeline

- **Sprint/Priority/Points:** 0 / Must / 5
- **Depends on:** CPS-001..003
- **Acceptance:** Husky pre-commit runs formatting, lint, typing, default tests, contract validation, and secret scan; infrastructure-backed gates are reserved for the GitLab pipeline.

## Epic CPS-E1 — Contracts, persistence, and operations

### CPS-101 — Canonical message envelope and schemas

- **Sprint/Priority/Points:** 1 / Must / 8
- **Depends on:** CPS-001
- **Coordinates with:** OPS-101
- **Tasks:** Pydantic models, JSON Schemas, schema-version rules, golden fixtures for command/progress/result/error/inventory batch, checksum manifest.
- **Acceptance:** all fixtures validate; unknown major version rejects; additive fields remain compatible; no event fixture contains credential/password/token.

### CPS-102 — Common error and API response model

- **Sprint/Priority/Points:** 1 / Must / 5
- **Depends on:** CPS-101
- **Acceptance:** validation, conflict, not-found, capability, provider, timeout, and internal errors use one safe envelope with stable codes and correlation ID.

### CPS-103 — Initial database migration and unit of work

- **Sprint/Priority/Points:** 1 / Must / 8
- **Depends on:** CPS-001
- **Tasks:** SQLAlchemy async engine/session, metadata conventions, provider/connection/credential/operation/event/inbox/outbox tables, Alembic baseline, repositories, transaction boundary.
- **Acceptance:** migration applies to empty PostgreSQL 18; constraints/indexes exist; rollback behavior is documented/tested; repository transaction tests pass.

### CPS-104 — Operation state machine and immutable history

- **Sprint/Priority/Points:** 1 / Must / 8
- **Depends on:** CPS-102, CPS-103
- **Acceptance:** only valid transitions succeed; terminal states are immutable; every transition appends ordered event; concurrent update conflict is detected; safe actor context is preserved.

### CPS-105 — Idempotent operation creation

- **Sprint/Priority/Points:** 1 / Must / 5
- **Depends on:** CPS-104
- **Acceptance:** same key and semantic request returns existing operation; same key with different request returns 409; concurrent identical requests create one operation.

### CPS-106 — Transactional outbox publisher and inbox consumer

- **Sprint/Priority/Points:** 1 / Must / 8
- **Depends on:** CPS-101, CPS-103
- **Acceptance:** operation/outbox commit atomically; publisher confirms before published state; retry schedule survives restart; inbox deduplicates by consumer/message; handler failure rolls back inbox/domain changes.

## Epic CPS-E2 — Provider connection vertical slice

### CPS-201 — Provider CRUD API

- **Sprint/Priority/Points:** 2 / Must / 5
- **Depends on:** CPS-102, CPS-103
- **Acceptance:** create/list/get/update provider; only supported provider type accepted; pagination/filter conventions apply; delete/disable behavior preserves referenced history.

### CPS-202 — Encrypted credential lifecycle

- **Sprint/Priority/Points:** 2 / Must / 8
- **Depends on:** CPS-103
- **Tasks:** encryption port/adapter, key versioning, create/update/delete metadata APIs, internal resolution service.
- **Acceptance:** plaintext never stored or returned publicly; rotation works; referenced credential cannot be deleted; wrong/missing key fails safely; redaction tests pass.

### CPS-203 — Provider connection API and invariants

- **Sprint/Priority/Points:** 2 / Must / 8
- **Depends on:** CPS-201, CPS-202
- **Acceptance:** one connection captures one project/region and username/password scope; optimistic versioning works; public responses omit secrets; status starts pending.

### CPS-204 — Internal credential resolution endpoint

- **Sprint/Priority/Points:** 2 / Must / 3
- **Depends on:** CPS-202, CPS-203
- **Coordinates with:** OPS-202
- **Acceptance:** internal route resolves only a valid referenced credential and connection data; excluded from public ingress/OpenAPI grouping; request/response logs redact secrets.

### CPS-205 — Async connection validation workflow

- **Sprint/Priority/Points:** 2 / Must / 8
- **Depends on:** CPS-104..106, CPS-203
- **Coordinates with:** OPS-201..204
- **Acceptance:** endpoint returns 202 and operation; command uses reference only; progress/result updates operation; successful capabilities persist; auth/unavailable failures map correctly; replay is safe.

### CPS-206 — Operation query APIs

- **Sprint/Priority/Points:** 2 / Must / 5
- **Depends on:** CPS-104
- **Acceptance:** list/get/events support stable pagination/filtering; terminal result/error is safe; unknown operation returns normalized 404.

## Epic CPS-E3 — Inventory and reconciliation

### CPS-301 — Typed inventory schema and migrations

- **Sprint/Priority/Points:** 3 / Must / 13
- **Depends on:** CPS-103
- **Tasks:** nine typed resource tables, instance-port/volume joins, lifecycle columns, provider identity and query indexes.
- **Acceptance:** uniqueness is per connection/resource table; relationships and soft delete work; migrations pass on PostgreSQL 18; representative query plans use intended indexes.

### CPS-302 — Inventory sync and batch persistence

- **Sprint/Priority/Points:** 3 / Must / 8
- **Depends on:** CPS-301, CPS-106
- **Coordinates with:** OPS-301..304
- **Acceptance:** batch deduplication and checksum rules work; out-of-order types persist; sequence conflict fails safely; unsupported collection is distinct from empty.

### CPS-303 — Safe full-sync finalization

- **Sprint/Priority/Points:** 3 / Must / 13
- **Depends on:** CPS-302
- **Acceptance:** only complete successful sync marks missing rows deleted; partial/failed/missing-last batch never deletes; relationships finalize; reappearing provider ID reactivates same CPS UUID; one active full sync per connection.

### CPS-304 — Inventory query APIs

- **Sprint/Priority/Points:** 3 / Must / 8
- **Depends on:** CPS-301
- **Acceptance:** list/get all scoped resource types; default hides deleted; `include_deleted` works; allow-listed filters/sorts and uniform pagination work; provider attributes remain versioned.

### CPS-305 — Manual full sync and targeted refresh APIs

- **Sprint/Priority/Points:** 3 / Must / 8
- **Depends on:** CPS-302, CPS-205
- **Coordinates with:** OPS-301, OPS-305
- **Acceptance:** endpoints create idempotent operations; duplicate full sync returns active operation; targeted not-found produces tombstone; provider timeout does not imply deletion.

## Epic CPS-E4 — VM lifecycle

### CPS-401 — VM create contract and validation

- **Sprint/Priority/Points:** 4 / Must / 8
- **Depends on:** CPS-101, CPS-304
- **Coordinates with:** OPS-401
- **Acceptance:** validates flavor/image/network/port/security-group ownership; supports IMAGE and VOLUME_FROM_IMAGE; requires explicit network; accepts safe optional key pair/user data/config drive; never logs user data.

### CPS-402 — VM create operation workflow

- **Sprint/Priority/Points:** 4 / Must / 8
- **Depends on:** CPS-401, CPS-105..106
- **Acceptance:** returns 202; publishes reference-only command; result atomically updates operation and normalized instance/relations; duplicate idempotency key cannot create two operations.

### CPS-403 — VM detail and power/delete workflows

- **Sprint/Priority/Points:** 4 / Must / 8
- **Depends on:** CPS-304, CPS-105..106
- **Coordinates with:** OPS-402..406
- **Acceptance:** detail/start/stop/reboot/delete use supported state/capability checks; result refreshes related inventory; delete creates tombstone; invalid state returns stable conflict.

### CPS-404 — Root-volume lifecycle persistence

- **Sprint/Priority/Points:** 4 / Must / 5
- **Depends on:** CPS-301, CPS-402
- **Acceptance:** boot source and delete-on-termination persist; local root disappears with VM; created Cinder root follows requested policy; CPS does not issue an independent blind volume delete.

## Epic CPS-E5 — Scheduling, recovery, and release

### CPS-501 — Inventory scheduler with jitter

- **Sprint/Priority/Points:** 5 / Should / 5
- **Depends on:** CPS-305
- **Acceptance:** per-connection schedule creates the same workflow as manual sync; jitter prevents synchronized starts; disabled/invalid connections skip safely; no scheduler performs provider I/O.

### CPS-502 — Operation timeout and late-result reconciliation

- **Sprint/Priority/Points:** 5 / Must / 8
- **Depends on:** CPS-104, CPS-106
- **Acceptance:** expired nonterminal operations become timed out with event; late result is retained without silently rewriting terminal state; reconciliation outcome is deterministic and observable.

### CPS-503 — DLQ and outbox/inbox operational controls

- **Sprint/Priority/Points:** 5 / Must / 5
- **Depends on:** CPS-106
- **Acceptance:** metrics expose backlog/redelivery/DLQ; safe replay procedure is documented/tested; poison messages cannot loop indefinitely; no payload secret is exposed.

### CPS-504 — Observability and LMS-ready audit projection

- **Sprint/Priority/Points:** 5 / Should / 5
- **Depends on:** CPS-104
- **Acceptance:** operation/correlation/provider/resource IDs propagate; metrics cover API/operation/sync/messaging; audit projection contains action/target/outcome/context without direct LMS dependency.

### CPS-505 — End-to-end recovery acceptance

- **Sprint/Priority/Points:** 5 / Must / 13
- **Depends on:** all Must CPS stories; paired OPS stories
- **Acceptance:** approved eight-scenario real-OpenStack suite passes, including service restarts, message replay, direct drift, both boot modes, and no lost operation.

## Deferred backlog

- Keycloak authentication/authorization and service-to-service identity.
- MS organization/domain and TMS workspace/project integration.
- LMS audit event publisher.
- VMware provider service.
- Webhook/SSE operation notifications.
- OpenStack notification-driven refresh.
- Cursor pagination migration if offset performance becomes insufficient.
- Shared contracts package after a second provider justifies it.
