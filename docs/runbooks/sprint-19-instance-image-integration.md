# Sprint 19 — instance snapshot integration evidence

## Automated evidence

- CPS focused: contract, durable-operation, catalog and inbox regression tests: 20 passed.
- OPS focused: pinned contract, snapshot handler, action/create and dispatch regressions: 43 passed.
- CPS full suite: 649 passed, 182 skipped (two pre-existing collection/deprecation warnings).
- OPS full suite: 470 passed, 24 skipped (one Starlette deprecation warning).
- Ruff, MyPy, and `git diff --check` passed in both repositories.

## Contract and safety

The request accepts only a source instance ID, owning project ID, image name,
and bounded string metadata. Image bytes, `user_data`, tokens, private-key
material, and secret-like metadata keys are rejected or absent. CPS derives a
deterministic operation/message identity from the idempotency key. OPS searches
Glance image metadata for that operation marker before issuing Nova
`create_server_image`, then waits only for a bounded terminal image state.

## Live acceptance and cleanup

Live execution passed: CPS instance create `019fc6a5-7223-702d-9d22-1c8d09403048`
created disposable server `d7ea87a6-492e-49f5-8e82-6459116ab60f`; snapshot
operation `71b28f7e-13d8-50d0-95b2-100148ff3f7c` returned image
`5ab875bd-27c8-4c59-9923-18280f7c5e06`. OpenStack CLI matched active
qcow2/bare/private snapshot metadata. A second CPS instance was launched from
that snapshot and then both servers plus the snapshot were deleted; CLI absence
was verified.

The disposable sequence is:
create an approved-image/flavor instance through CPS; request the member
instance-snapshot endpoint with an idempotency key; poll to terminal success;
compare returned image ID/name/status/source metadata with `openstack image
show`; use the snapshot in a CPS instance operation; delete the disposable
server and image through CPS; refresh and prove absence via both CPS and
OpenStack CLI. This document deliberately records no credentials, tokens,
authorization headers, image bytes, or provider response bodies.
