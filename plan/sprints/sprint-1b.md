# Sprint 1B — Persistence, operations, and messaging

**Status:** Done
**Dates:** closed **2026-07-22** after CP6 evidence review and independent approval
**Capacity:** 21 committed points in 1B-Must; 21 stretch points in 1B-Messaging (both increments delivered)
**Sprint Goal:** CPS persists provider metadata, operations, and reliable outbox/inbox; OPS runs a complete RabbitMQ runtime with envelope validation and handler dispatch — without OpenStack calls, credential resolution, or provider CRUD APIs.

## Committed stories — 1B-Must

| Story | Points | Repo | Depends on | Increment | Status |
|---|---:|---|---|---|---|
| CPS-103 — Initial database migration and unit of work | 8 | CPS | CPS-001 | 1B-Must | Done |
| CPS-104 — Operation state machine and immutable history | 8 | CPS | CPS-102, CPS-103 | 1B-Must | Done |
| CPS-105 — Idempotent operation creation | 5 | CPS | CPS-104 | 1B-Must | Done |

**Committed total:** 21 points — all Done.

## Stretch — 1B-Messaging

| Story | Points | Repo | Depends on | Status |
|---|---:|---|---|---|
| OPS-102 — RabbitMQ topology and robust runtime | 8 | OPS | OPS-001, OPS-101, transport contract | Done |
| OPS-104 — Handler dispatch and envelope validation | 5 | OPS | OPS-101..103, OPS-102 | Done |
| CPS-106 — Transactional outbox publisher and inbox consumer | 8 | CPS | CPS-101, CPS-103, OPS-102 | Done |

**Stretch total:** 21 points — all Done.

## Deferred (not Sprint 1B — Sprint 2+)

- Provider/credential/connection CRUD APIs (CPS-201..203).
- OPS credential resolver and OpenStack handlers (OPS-201+).
- Inventory tables and sync (CPS-301+, OPS-301+).
- VM lifecycle APIs and real OpenStack integration.
- Keycloak, TMS, LMS, and CMP integration.
- Valkey runtime dependency in CPS.

## Delivery order and review checkpoints

1. **CP1 — CPS-103:** schema + Alembic + async UoW on empty PostgreSQL 18 — **Done**
2. **CP2 — CPS-104 + CPS-105:** state machine, history, idempotency races — **Done**
3. **CP3 — Contract delta:** CPS canonical fixtures/schemas + OPS pin — **Done**
4. **CP4 — OPS-102:** full topology, confirms, retry/DLX, reconnect, shutdown — **Done**
5. **CP5 — OPS-104:** envelope validation and typed dispatch (no OpenStack) — **Done**
6. **CP6 — CPS-106 + cross-repo integration:** outbox/inbox with RabbitMQ fakes/live Compose — **Done**

## Definition of Done

All items in the canonical plan §Definition of Done are satisfied with fresh evidence dated **2026-07-22**. See `docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md` §Sprint 1B closure evidence.

## Review evidence

- Verification date: **2026-07-22** (Task 12 closure gate; CPS HEAD `f095321248ab46dda72425f9da181b63caeffa9c`, OPS HEAD `7318f53ee29f5e54a25b4dd0fd35034591cc0854`).
- Task/story matrix: **12/12 tasks Done**, **6/6 stories Done** (see canonical plan for per-task commits).
- Independent review: **APPROVED** — no P0–P3; ready to close.
- Cross-repo contract byte parity SHA-256: `2C19CB44550063383F4EBCD35E292B5377FEEDFC185B30F215117E6EA150A07D` (10 artifacts byte-equal; exact `x-*` headers and routing keys).
- CPS gates (exit 0): OFF pytest **413 passed, 189 skipped**; DB integration **142 passed**; messaging **45 passed**; full integration ON **600 passed, 2 skipped**; Alembic empty→head→base→head; `uv lock --check` / `uv sync --frozen --all-extras`; Ruff format (**150** files), Ruff check, mypy (**79** files), contracts validate (**10** artifacts), `git diff --check`; Docker build `cps:sprint1b`; host `.husky/pre-commit` (including staged fix state); secret scan baseline unchanged `D44DC71F8B1CE2D873CE45D7A13781E0A361B68979A137A8D37A06E031E81BDE`.
- OPS gates (exit 0): OFF pytest **311 passed, 24 skipped**; messaging **21 passed**; full integration ON **333 passed, 2 skipped**; OpenStack DeprecationWarning suite **42 passed** (`-W error::DeprecationWarning`); `uv lock/sync`, Ruff format (**86** files) / check, mypy (**47** files), contracts validate (**10**), standalone pin, `git diff --check`; Docker build `ops:sprint1b`; host `.husky/pre-commit`; secret scan baseline unchanged `48EBCA6C0199E4331362AF974970DD49528CEAEB16C483208F0A226CF4058E8F`.
- Boundaries: no OpenStackSDK in CPS; no DB runtime in OPS; no sibling imports, legacy `cpms`/`osps` paths, or GitHub Actions; readiness boundaries pass.
- Warnings: 1 known `StarletteDeprecationWarning` (httpx vs httpx2 in FastAPI test client) in both repos — pre-existing, non-blocking.

## Sprint Review

- CPS-103 delivered PostgreSQL 18 schema (seven tables), Alembic revision, async UoW, AES-GCM credential boundary, and provider/connection repositories.
- CPS-104 delivered operation state machine, immutable event history, and optimistic concurrency.
- CPS-105 delivered idempotent operation creation with fingerprint semantics and race-safe unique index handling.
- CPS-106 delivered transactional outbox (leased SKIP LOCKED, publisher confirms) and inbox deduplication with cross-repo OPS stub integration.
- OPS-102 delivered RabbitMQ topology, consumer ack/retry/DLQ matrix, publisher confirms, reconnect, and graceful shutdown.
- OPS-104 delivered envelope validation and typed handler dispatch (stub only — no OpenStack).
- Transport contract delta (`DeliveryMetadata`) pinned byte-for-byte across repos.

## Sprint Retrospective

- **Keep:** disposable test guards; contract byte-parity gates; exact ACK/confirm ordering tests; leased outbox claims; inbox `(consumer_name, message_id)` dedupe; NUL-safe secret scan over tracked paths.
- **Improve:** continue per-task commit boundaries when history allows; record verification HEADs explicitly at closure (no self-referential docs-only commit SHA).
- **Sprint 2 handoff:** provider CRUD, credential resolver, real OpenStack handlers, inventory/VM lifecycle, and Keycloak/TMS/LMS/CMP remain deferred per product backlog.

## Implementation plan

- **Canonical:** `docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`
- **OPS working copy:** `../ops/docs/superpowers/plans/2026-07-20-sprint-1b-persistence-operations-messaging.md`
