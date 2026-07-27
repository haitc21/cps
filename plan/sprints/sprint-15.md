# Sprint 15 — CMP user block-storage lifecycle

**Status:** Done
**Dates:** TBD at Sprint Planning
**Capacity:** 29 CPS points
**Sprint Goal:** An authorized workspace user can create, attach, detach,
extend, and delete a project-owned Cinder volume through durable CPS/OPS
operations.

**Plan:** `../../docs/superpowers/plans/2026-07-27-cmp-user-resource-completion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1501 Project-owned volume inventory and API | 8 | CPS | OPS-1501 | Done |
| CPS-1502 Volume create/update/extend/delete | 8 | CPS | OPS-1502 | Done |
| CPS-1503 Volume attach/detach | 8 | CPS | OPS-1503 | Done |
| CPS-1504 Storage vertical acceptance | 5 | CPS/OPS | OPS-1501..1503 | Done |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1501](../tasks/sprint-15/CPS-1501-volume-inventory-api.md) | Typed project-owned volume inventory and query APIs | CPS-1202, CPS-1203 | Done |
| [CPS-1502](../tasks/sprint-15/CPS-1502-volume-lifecycle.md) | Durable volume create/update/extend/delete | CPS-1501 | Done |
| [CPS-1503](../tasks/sprint-15/CPS-1503-volume-attachment.md) | Replay-safe attach/detach relationships | CPS-1501, CPS-403 | Done |
| [CPS-1504](../tasks/sprint-15/CPS-1504-storage-acceptance.md) | Restart/redelivery and real-cloud storage acceptance | CPS-1501..1503 | Done |

## Execution sequence

1. Pin volume, attachment, progress, result, and tombstone contracts.
2. Add ownership-aware volume persistence and reconciliation.
3. Deliver create/update/extend/delete as one guarded operation family.
4. Deliver attach/detach with dual-resource ownership and state checks.
5. Run disposable real-cloud workflow and verify cleanup.

## Acceptance

- Cross-workspace volume access is denied before command publication.
- Size never decreases; root or attached volume deletion fails safely.
- Duplicate commands cannot create duplicate volumes or attachments.
- Full/targeted inventory converges after each mutation.
- CPS/OPS restart and terminal publish redelivery retain deterministic history.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Cinder status differs by backend | OPS | Capability/state mapping and bounded waiter | Open |
| Root/data volume ownership is ambiguous | CPS/OPS | Persist boot/root flags and refuse unsafe delete | Open |
| Multiattach is unsupported on some clouds | OPS | Capability-gate and default deny | Open |

## Review evidence

- Contract checksum:
- Migration lifecycle:
- Restart/redelivery:
- Real-cloud resource IDs and cleanup:
