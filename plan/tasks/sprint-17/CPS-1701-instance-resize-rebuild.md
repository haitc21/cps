# CPS-1701 — Instance resize and rebuild

**Status:** In progress
**Points:** 13
**Depends on:** CPS-403, CPS-1203, CPS-1703
**Paired task:** OPS-1701

## Outcome

Workspace users resize and rebuild owned instances using approved catalog
resources with deterministic recovery.

## Change set

- Add resize request/confirm/revert state machine and timeout reconciliation.
- Add rebuild request using an approved image while preserving explicit network,
  keypair, metadata, and root-volume policy.
- Normalize Nova intermediate/error states and refresh relationships.

## Required tests

- Resize success, confirm, revert, timeout, restart, and invalid-state conflict.
- Rebuild approved/unapproved image, volume-backed constraints, provider error,
  ownership denial, and result redelivery.

## Implementation note

The instance contract now carries resize, confirm-resize, revert-resize, and
rebuild actions. Resize/rebuild references are checked against the approved
catalog before CPS publishes a command; OPS maps them to Nova's resize,
confirm, revert, and rebuild calls.

## Done when

Both operations converge in CPS inventory/history and pass disposable
real-cloud recovery scenarios.
