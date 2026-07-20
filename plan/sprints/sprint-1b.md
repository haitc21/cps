# Sprint 1B — Persistence, operations, and messaging

**Dates:** starts after plan approval; closes only after CP6 evidence review
**Capacity:** 21 committed points in 1B-Must; 21 stretch points in the separately gated 1B-Messaging increment
**Sprint Goal:** CPS persists provider metadata, operations, and reliable outbox/inbox; OPS runs a complete RabbitMQ runtime with envelope validation and handler dispatch — without OpenStack calls, credential resolution, or provider CRUD APIs.

## Committed stories — 1B-Must

| Story | Points | Repo | Depends on | Increment |
|---|---:|---|---|---|
| CPS-103 — Initial database migration and unit of work | 8 | CPS | CPS-001 | 1B-Must |
| CPS-104 — Operation state machine and immutable history | 8 | CPS | CPS-102, CPS-103 | 1B-Must |
| CPS-105 — Idempotent operation creation | 5 | CPS | CPS-104 | 1B-Must |
**Committed total:** 21 points.

## Stretch — 1B-Messaging (starts only after CP2 review)

| Story | Points | Repo | Depends on |
|---|---:|---|---|
| OPS-102 — RabbitMQ topology and robust runtime | 8 | OPS | OPS-001, OPS-101, transport contract |
| OPS-104 — Handler dispatch and envelope validation | 5 | OPS | OPS-101..103, OPS-102 |
| CPS-106 — Transactional outbox publisher and inbox consumer | 8 | CPS | CPS-101, CPS-103, OPS-102 |

**Stretch total:** 21 points. Stretch stories remain Ready until their increment is explicitly started; none is partially marked Done.

## Deferred (not Sprint 1B)

- Provider/credential/connection CRUD APIs (CPS-201..203).
- OPS credential resolver and OpenStack handlers (OPS-201+).
- Inventory tables and sync (CPS-301+, OPS-301+).
- Valkey runtime dependency in CPS.

## Delivery order and review checkpoints

1. **CP1 — CPS-103:** schema + Alembic + async UoW on empty PostgreSQL 18.
2. **CP2 — CPS-104 + CPS-105:** state machine, history, idempotency races.
3. **CP3 — Contract delta (if required):** CPS canonical fixtures/schemas + OPS pin.
4. **CP4 — OPS-102:** full topology, confirms, retry/DLX, reconnect, shutdown.
5. **CP5 — OPS-104:** envelope validation and typed dispatch (no OpenStack).
6. **CP6 — CPS-106 + cross-repo integration:** outbox/inbox with RabbitMQ fakes/live Compose.

## Definition of Done

See canonical plan §Definition of Done: `docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`.

## Implementation plan

- **Canonical:** `docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`
- **OPS working copy:** `../ops/docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`
