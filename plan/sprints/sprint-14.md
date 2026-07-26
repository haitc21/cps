# Sprint 14 — VM create terminal convergence and recovery

**Status:** Ready for implementation  
**Dates:** 2026-10-03 to 2026-10-16  
**Capacity:** 13 CPS points  
**Sprint Goal:** Every CPS VM-create operation reaches one deterministic terminal
state even when Nova has already created the server but OPS enrichment, result
publication, redelivery, or worker restart is interrupted.

**Repository constraint:** Only CPS and the paired OPS contract may change.
TMS, LMS, and BMS are out of scope.

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1301 Persist early provider identity and terminal events | 5 | CPS | OPS-1301, OPS-1303 | Ready |
| CPS-1302 Reconcile stale VM-create operations | 8 | CPS | OPS-1304 | Ready |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1301](../tasks/sprint-14/CPS-1301-provider-identity-terminal-events.md) | Persist Nova server identity from progress and consume terminal events idempotently | OPS-1301, OPS-1303 | Ready |
| [CPS-1302](../tasks/sprint-14/CPS-1302-stale-operation-reconciliation.md) | Detect and reconcile stale VM-create operations through OPS | CPS-1301, OPS-1304 | Ready |

## Execution sequence

1. Pin the progress, completed, failed, and reconcile command/result contract.
2. Complete CPS-1301 and prove duplicate/late terminal events are deterministic.
3. Complete CPS-1302 with bounded retry and operation-timeout scheduling.
4. Run the joint restart, result-publish-failure, and real OpenStack acceptance
   scenarios.
5. Verify BMS, TMS, and LMS contain no sprint diff.

## Acceptance

- CPS persists `provider_resource_id` as soon as OPS reports the created Nova
  server, before optional relationship enrichment finishes.
- A completed or failed event is idempotent and cannot corrupt an already
  terminal operation.
- A nonterminal VM-create operation that exceeds its convergence threshold
  causes a reconciliation command; CPS never calls OpenStack directly.
- Reconciliation maps provider `ACTIVE` or `SHUTOFF` to `SUCCEEDED`, `ERROR` to
  `FAILED`, and confirmed absence after the deadline to `TIMED_OUT`.
- A late result is retained as evidence and handled according to the operation
  state-machine policy without silently rewriting terminal history.
- The acceptance operation whose Nova server is
  `a64e3ca9-d396-4357-8396-fd989ad288ce` can converge from `RUNNING` at 20
  percent to `SUCCEEDED` when the server remains `ACTIVE`.
- CPS and OPS contract, unit, integration, restart, redelivery, migration, and
  real OpenStack acceptance gates pass.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| A progress event arrives without a provider resource ID | CPS/OPS | Version and validate the create-progress payload; reconcile by operation marker only as fallback | Open |
| A terminal event arrives after CPS has timed out the operation | CPS | Preserve immutable history and record the late provider outcome explicitly | Open |
| Reconciliation produces excessive provider traffic | CPS | Indexed stale-operation scan, jitter, bounded batches, exponential backoff | Open |

## Review evidence

- Progress persistence and duplicate-event tests:
- Stale-operation scheduler/reconciler tests:
- OPS restart and terminal publish recovery:
- Real OpenStack VM-create acceptance:
- Verification that BMS/TMS/LMS have no diff:

## Retrospective actions

- Keep:
- Improve:
- One measurable action for the next sprint:
