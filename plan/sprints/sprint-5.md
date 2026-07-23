# Sprint 5 — Scheduling, recovery, and release readiness

**Status:** Complete — implementation, regression gates, and live acceptance recorded
**Goal:** Make CPS/OPS recoverable, observable, replay-safe, and ready for repeatable release acceptance.
**Canonical executable plan:** `docs/superpowers/plans/2026-07-23-sprint-5-recovery-release.md`

## Scope

| Story | Points | Status | Acceptance gate |
|---|---:|---|---|
| CPS-501 Inventory scheduler with jitter | 5 | Done | eligible-connection filtering, capability metadata parsing, jitter tests |
| CPS-502 Operation timeout and late-result reconciliation | 8 | Done | durable timeout transition/event, timeout metric, recovery tests |
| CPS-503 DLQ and outbox/inbox operational controls | 5 | Done | bounded topology/retry controls, metrics and replay runbook |
| CPS-504 Observability and LMS-ready audit projection | 5 | Done | metrics endpoint and LMS-independent audit projection |
| CPS-505 End-to-end recovery acceptance | 13 | Done | worker restart/readiness, validation, replay, audit, and Sprint 4 VM evidence |
| OPS-501 Stateless replay safety | 13 | Done | existing provider markers/state reconciliation plus replay regression suite |
| OPS-502 Concurrency, backpressure, and graceful shutdown | 8 | Done | configurable prefetch, bounded drain, retry/DLQ regression suite |
| OPS-503 Provider observability | 5 | Done | handler call/error/duration counters and safe logs |
| OPS-504 Mocked integration suite | 8 | Done | unit/contract/integration recovery matrix |
| OPS-505 Real OpenStack acceptance report | 13 | Done | live capability validation and prior VM lifecycle acceptance evidence |

## Definition of Done

- Focused and affected-suite tests pass for every implemented story.
- No provider I/O occurs in CPS scheduler code.
- Timeout and late-result state transitions are durable and observable.
- DLQ/retry controls are bounded and documented; secrets never appear in diagnostics.
- Worker restart/shutdown preserves durable CPS/provider truth and does not create duplicate VMs.
- Live recovery acceptance is recorded with environment limitations explicitly stated.

## Evidence

- CPS: `ruff`, `mypy`, `393 passed, 2 skipped` unit tests; `82 passed, 189 skipped` contract/integration tests.
- OPS: `ruff`, `mypy`, `332 passed, 24 skipped` unit/contract/integration tests.
- Live: CPS public `:8000`, internal `:8002`, CPS worker, and OPS worker healthy; RabbitMQ queues empty on command/event paths and both consumers active with prefetch 10.
- Live operation `019f8dc7-f696-7bbd-9d7a-b46ea079a95b` reached `SUCCEEDED`; same idempotency key returned the same operation; audit projection returned 6 events.
- Sprint 4 VM lifecycle evidence covers both `IMAGE` and `VOLUME_FROM_IMAGE` boot modes. The volume delete caveat remains documented in the Sprint 4 evidence.
- Deployment note: OPS must set `OPS_CPS_BASE_URL` to the CPS internal resolver listener (`:8002` in the development environment); pointing to the public listener produces a credential-resolution 404.
