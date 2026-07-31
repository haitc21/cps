# CPS-1701 — Instance resize and rebuild

**Status:** Done
**Active backlog:** No
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

CPS also rejects actions whose latest inventoried Nova state is incompatible
before publishing. OPS independently rechecks provider state and treats retry
deliveries already in `RESIZE`, `VERIFY_RESIZE`, or `REBUILD` as convergence
work instead of issuing the mutation again. Invalid states produce the stable
`INVALID_RESOURCE_STATE` conflict.

## Review evidence

- CPS unit/contract/full suite: resize, confirm, revert, and rebuild invalid
  states are rejected before publication; approved catalog references remain
  contract-covered.
- OPS unit/full suite: resize success, confirm/revert success, invalid-state
  conflict, and timeout/redelivery convergence without duplicate resize or
  rebuild mutation.
- Reviewer caught and corrected the OpenStackSDK method mapping to
  `confirm_server_resize` and `revert_server_resize`; focused regression tests
  cover the exact adapter calls.
- Live OpenStack acceptance on `cmp-dev`:
  - resize and revert succeeded:
    `019fb66a-c61e-734b-9255-864bbcb8c9e1`,
    `019fb66b-3bb9-7289-a438-833970695861`;
  - rebuild from the approved Ubuntu image succeeded:
    `019fb66b-8b69-76b0-a57e-eaefd353c411`;
  - final resize/confirm restored `n1.small`:
    `019fb66c-ad80-7232-8ba9-04c34d530e60`,
    `019fb66e-0924-78d3-bca5-7d77d790a875`;
  - SSH after rebuild succeeded to `cmp-dev` at `192.168.57.190`.
- Disposable flavor was removed and `n1.normal` was restored to 2 vCPU,
  4096 MiB RAM, 40 GiB disk with the approved catalog marker.

## Done when

Both operations converge in CPS inventory/history and pass disposable
real-cloud recovery scenarios.
