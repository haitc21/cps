# CPS-1701 — Instance resize and rebuild

**Status:** Needs refinement
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

## Done when

Both operations converge in CPS inventory/history and pass disposable
real-cloud recovery scenarios.

