# Sprint 2 — Provider validation vertical slice

**Status:** Complete — real OpenStack acceptance verified
**Dates:** 2026-07-22 onward; close only after real OpenStack acceptance
**Goal:** Manage one OpenStack provider connection from CPS API through OPS safe-read validation and back to durable CPS capabilities.
**Canonical design:** `docs/superpowers/specs/2026-07-22-sprint-2-provider-validation-spec.md`
**Canonical executable plan:** `docs/superpowers/plans/2026-07-22-sprint-2-provider-validation.md`

## Scope and story backlog

| Story | Points | Status | Acceptance gate |
|---|---:|---|---|
| CPS-201 Provider CRUD API | 5 | Complete | CRUD, paging/filtering, optimistic version, disable referenced provider |
| CPS-202 Encrypted credential lifecycle | 8 | Complete | username/password encryption, rotation, fail-closed keys, redaction |
| CPS-203 Provider connection API | 8 | Complete | one project/domain/region identity, pending status, safe response |
| CPS-204 Internal credential resolution | 3 | Complete | pair validation, handler-scope plaintext, internal-only OpenAPI exclusion |
| CPS-205 Async connection validation | 8 | Complete | 202, atomic operation/outbox, inbox capabilities, replay safety |
| CPS-206 Operation query APIs | 5 | Complete | list/get/events, stable paging, safe terminal payload |

**CPS total:** 37 points. **OPS coordination:** OPS-201..204, 26 points. Inventory, VM lifecycle,
Keycloak, MS/TMS/LMS/CMP, multi-region, UI, and Sprint 3 are explicitly deferred.

## Checkpoints

| Checkpoint | Deliverable | Status |
|---|---|---|
| CP0 | Ubuntu readiness, portability, hardened staged secret gate | Done — CPS `b05ea02`, OPS `89173ba` |
| CP1 | Canonical schemas, API decisions, migration/security foundation | Done |
| CP2 | CPS-201 provider CRUD | Done |
| CP3 | CPS-202 encrypted credentials | Done |
| CP4 | CPS-203 connection API | Done |
| CP5 | CPS-206 operation query | Done |
| CP6 | CPS-204 internal resolution | Done |
| CP7 | OPS-201 CPS resolver | Done |
| CP8 | OPS-202 SDK factory | Done |
| CP9 | OPS-203 discovery/capabilities + multi-event transport | Done |
| CP10 | OPS-204 validation handler | Done |
| CP11 | CPS-205 async workflow/inbox persistence | Done |
| CP12 | Synthetic integration and real OpenStack acceptance | Done — real controller validation verified |
| CP13 | Full verification, evidence, closure | Done |

## CP0 evidence

Ubuntu 26.04 LTS, Bash 5.3.9, CPython 3.12.13, uv 0.11.31, Docker 29.3.1/Compose 5.1.1,
CodeGraph 1.2.0, RTK 0.43.0, Codex CLI 0.145.0, ShellCheck 0.11.0, and shfmt 3.13.1 were
detected. PostgreSQL 18, RabbitMQ 4.1, and Valkey 9.1 development containers were healthy.
No tracked project-relevant PowerShell script exists; the existing Husky shell gate was hardened
and active Ubuntu documentation was corrected. CPS/OPS worktrees were clean and synchronized.

The OpenStack VMs are reachable from the host. The host-side route was verified through
`controller -> 192.168.122.253`; the mapping is local runtime configuration only and no credentials
were committed.

## Definition of Done

All six CPS stories and coordinated OPS stories have pushed commits; canonical contracts are pinned;
migrations pass upgrade/downgrade/upgrade; CPS/OPS full gates, Docker builds, pre-commit, and secret
checks pass; the product path succeeds against real OpenStack with safe-read-only calls; evidence
contains no secrets; both repositories are clean/upstream-synchronized. Do not mark Done on unit
tests alone or begin Sprint 3.

## Implementation and evidence

Follow the canonical executable plan task-by-task. Each Cursor task must produce RED/GREEN evidence;
Codex reviews the diff and blast radius; Codex commits/pushes only after focused, affected integration,
full, pre-commit, contract, and security gates pass. Add task SHAs, fresh counts, checksums, Docker
results, and real OpenStack operation/capability IDs here only at closure.

### CP1 Task 1 evidence — 2026-07-22

- RED: missing `cps.contracts.validation` import, as expected.
- GREEN: CPS contract suite 71 passed; OPS pinned contract suite 81 passed.
- Both contract validators report 12 artifacts, checksum manifests match, and Ruff/diff checks pass.
- Scope remains safe-read validation only; provider/credential public API implementation has not started.

### CP1 Task 2 foundation evidence — 2026-07-22

- Added the reversible credential/operation migration, field-labeled AES-GCM helpers, and fail-closed
  external key-ring parsing. API/UoW and credential lifecycle work remains in progress.
- CPS unit suite: 434 passed, 2 skipped in focused run; PostgreSQL 18 migration/schema integration: 143 passed.

### CP2 provider CRUD implementation evidence — 2026-07-22

- Added durable FastAPI create/list/get/PATCH routes with PostgreSQL UoW ownership,
  UUIDv7 IDs, stable name/ID ordering, status/name filtering, and optimistic version updates.
- Local Docker API smoke: create 201, list 200, patch 200/version 2, stale patch 409 with
  `VERSION_CONFLICT`; smoke row was removed afterward.
- CPS unit + contract suites: 432 passed, 2 skipped; mypy, Ruff, and diff checks pass.

### CP3 credential lifecycle evidence — 2026-07-22

- Added encrypted username/password persistence, metadata-only public responses, active key-ring
  wiring, optimistic update, rotation timestamp, and reference-protected deletion.
- Docker PostgreSQL smoke: create 201 with no secret in response, update version 2, delete 204;
  read-only catalog check found zero plaintext username rows and zero remaining credential rows.
- Clean-room migration/schema integration remains green: 143 passed.

### Sprint 2 implementation evidence — 2026-07-22

- CPS connection API, internal resolver, validation command, operation list/get/events, and inbox
  capability persistence are implemented. Docker API smoke reached 202 Accepted, replayed the same
  operation for the same idempotency key, and returned only safe public projections.
- OPS now resolves credential references over bounded HTTP, constructs an ephemeral OpenStackSDK
  connection, performs authentication/catalog discovery only, emits deterministic ordered progress
  and terminal events, and confirms all events before one broker ACK.
- CPS full suite: 434 passed, 190 skipped. OPS full suite: 323 passed, 24 skipped. CPS disposable
  PostgreSQL 18 integration: 143 passed. Contract validators: 12 artifacts each; manifests and
  CPS pin match. Ruff and mypy pass for both repositories.
- Event application smoke verified `RUNNING → WAITING_PROVIDER → SUCCEEDED`, durable capability
  persistence, and `validated_at` in the same CPS transaction. Local smoke data was truncated.
- Real OpenStack acceptance passed through the host route using the disposable local DB: operation
  `019f8bdb-229a-78c2-847f-5a42508fde89` reached `SUCCEEDED`, connection
  `019f8bd8-43d5-76eb-9b8c-fe6e49254b82` reached `VALID`, and events were
  `QUEUED → RUNNING → PROGRESS → SUCCEEDED`. The capability result reported identity, compute,
  network, and image available; block storage was safely reported unavailable. Runtime smoke also
  exposed and fixed CPS outbox dispatch and private-listener CLI wiring gaps.
- The migration now drops plaintext `credentials.username` at head, requires encrypted username
  ciphertext/nonce, restores the legacy shape only on empty downgrade, and rejects non-empty legacy
  upgrades without copying plaintext.
