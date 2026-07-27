# CPS-1503 — Volume attach/detach

**Status:** Ready
**Points:** 8
**Depends on:** CPS-1501, CPS-403
**Paired task:** OPS-1503

## Outcome

Users attach and detach data volumes only when the volume and instance belong
to the same authorized workspace and are in compatible states.

## Change set

- Define attachment identity and ensure/remove semantics.
- Validate both resources and canonical project ownership in CPS and OPS.
- Capability-gate multiattach and normalize provider device/attachment IDs.
- Refresh instance-volume relationships after terminal outcomes.

## Required tests

- Same-project attach/detach succeeds; cross-project reference publishes
  nothing.
- Duplicate attach/detach converges.
- Attached-to-other-instance, invalid state, absent relation, and multiattach
  denial are deterministic.
- Partial provider mutation and result-publish failure recover after restart.

## Done when

Attachment inventory and operation history agree after success, redelivery,
drift, and cleanup.

