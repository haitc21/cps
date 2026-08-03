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

Pending paired CPS/OPS live execution. The required disposable sequence is:
create an approved-image/flavor instance through CPS; request the member
instance-snapshot endpoint with an idempotency key; poll to terminal success;
compare returned image ID/name/status/source metadata with `openstack image
show`; use the snapshot in a CPS instance operation; delete the disposable
server and image through CPS; refresh and prove absence via both CPS and
OpenStack CLI. This document deliberately records no credentials, tokens,
authorization headers, image bytes, or provider response bodies.
