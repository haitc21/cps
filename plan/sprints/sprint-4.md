# Sprint 4 — VM lifecycle

**Status:** Complete with provider caveat — code, regression gates, and both live boot paths passed; dev Nova/Cinder did not honor root-volume deletion on VM delete
**Goal:** Create and operate OpenStack VMs through CPS/OPS with durable, idempotent lifecycle workflows for both supported boot modes.
**Canonical design:** `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`
**Canonical executable plan:** `docs/superpowers/plans/2026-07-23-sprint-4-vm-lifecycle.md`

## Scope and story backlog

| Story | Points | Status | Acceptance gate |
|---|---:|---|---|
| CPS-401 VM create contract and validation | 8 | Done | ownership checks, explicit network, safe optional fields, no user-data leakage |
| CPS-402 VM create operation workflow | 8 | Done | 202 operation, reference-only command, idempotent terminal instance persistence |
| CPS-403 VM detail and power/delete workflows | 8 | Done | state/capability checks, normalized result, tombstone and stable conflicts |
| CPS-404 Root-volume lifecycle persistence | 5 | Done | boot source and delete-on-termination policy persist without blind volume delete |
| OPS-401 Create VM handler | 13 | Done | IMAGE and VOLUME_FROM_IMAGE mapping, marker/replay safety, bounded user data |
| OPS-402 Instance detail operation | 5 | Done | normalized instance plus related port/volume snapshots |
| OPS-403 Start and stop handlers | 8 | Done | preconditions, waiter, replay-safe result |
| OPS-404 Reboot handler | 5 | Done | reboot type mapping, waiter and normalized errors |
| OPS-405 Delete handler and root-volume semantics | 8 | Done | Nova delete-on-termination semantics and related refresh |
| OPS-406 Common waiter layer | 8 | Done | deterministic clock/sleeper, terminal and timeout handling |

**CPS total:** 29 points. **OPS total:** 47 points.

## Delivery order

1. CPS-401 + OPS-406: canonical VM request/result contracts and waiter primitives.
2. CPS-402 + OPS-401: create workflow, both boot modes, marker and normalized persistence.
3. CPS-403/404 + OPS-402..405: detail, power, reboot, delete, and root-volume policy.
4. Cross-service mocked integration and real OpenStack lifecycle acceptance.

## Definition of Done

- Every story has focused acceptance tests, affected-suite tests, and reviewer evidence.
- CPS canonical contracts are pinned into OPS before handler behavior is merged.
- User data, credentials, provider SDK objects, and tokens never enter logs, fixtures, or persisted operation payloads.
- Create is idempotent and replay-safe; lifecycle mutations use provider state checks and waiters.
- Both IMAGE and VOLUME_FROM_IMAGE paths are exercised; root-volume deletion is delegated to Nova policy.
- Full CPS/OPS gates, migration checks, and live acceptance pass before closure.

## Current evidence

- 2026-07-23: Sprint 4 scope selected from CPS-E4/OPS-E4 after Sprint 3 closure; all dependencies are available on pushed Sprint 3 baseline.
- 2026-07-23: CPS-401 contract slice added with explicit network/port requirement, IMAGE/VOLUME_FROM_IMAGE validation, bounded optional fields, and action payload validation; focused contract tests pass.
- 2026-07-23: OPS-406 waiter primitive added with injectable clock/sleeper and target/error/timeout behavior; focused waiter tests pass. OPS-401 create mapping now covers both boot source request shapes, operation marker metadata, and base64 user-data forwarding without logging it.
- 2026-07-23: CPS lifecycle command creation and OPS detail/start/stop/reboot/delete handler registration added; full contract/unit regression currently passes CPS `469 passed, 2 skipped` and OPS `331 passed, 2 skipped`. Persistence of normalized lifecycle results and real VM acceptance remain open before closure.
- 2026-07-23: CPS operation completion now persists normalized instance results transactionally; OPS start/stop/reboot paths wait for target provider state and delete emits an idempotent DELETED result. Related port snapshots and root-volume policy are covered; live acceptance is recorded below.
- 2026-07-23: Live OpenStack acceptance passed with temporary `compute02` instance: IMAGE create, GET, START, STOP, START, HARD REBOOT, and DELETE all reached `SUCCEEDED`; final `openstack server list --name compute02` was empty. SOFT REBOOT returned the dev cloud's stable 409 conflict; HARD REBOOT passed.
- 2026-07-23: After Cinder became available, `VOLUME_FROM_IMAGE` create reached `SUCCEEDED` and CPS persisted the attached root volume relationship. VM DELETE reached `SUCCEEDED`, but the dev Nova/Cinder deployment left the root volume `in-use` despite `delete_on_termination=true`; the stale attachment and volume were cleaned manually. This is a provider behavior deviation requiring infrastructure remediation for a fully clean root-volume deletion gate.
- 2026-07-23: Final gates pass: CPS `469 passed, 2 skipped`; OPS `331 passed, 2 skipped`; Ruff and mypy pass in both repositories; `git diff --check` passes.
