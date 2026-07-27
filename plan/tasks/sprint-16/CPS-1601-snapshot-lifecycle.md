# CPS-1601 — Volume snapshot lifecycle

**Status:** Blocked by Sprint 15
**Points:** 8
**Depends on:** CPS-1501..1503
**Paired task:** OPS-1601

## Outcome

Workspace users inventory, create, rename, delete, and use snapshots as a
source for new project-owned volumes.

## Change set

- Add typed snapshot inventory, ownership, source-volume relationship,
  lifecycle contracts, fixtures, persistence, query, and tombstones.
- Add create/update/delete operations and `volume.create` snapshot-source
  reference.
- Use bounded waiters and deterministic recovery after unknown provider outcome.
- Refuse cross-project sources and unsafe delete dependencies.

## Required tests

- Create replay, timeout after mutation, delayed availability, absent delete,
  cross-project denial, clone-volume convergence, and cleanup.

## Done when

Snapshot and cloned volume converge in inventory with restart/redelivery and
real-cloud evidence.

