# CPS-1906 — Horizon parity contract and presentation API

**Status:** Deferred — implementation committed; TMS integration and OpenStack scope-policy closure pending  
**Points:** 8  
**Paired task:** OPS-1906

## Testable outcome

An authorized API consumer can use one stable CPS contract for flavor/image list, detail,
filters, capabilities, allowed actions, durable mutation submission, and
operation polling without knowing Nova, Glance, or RabbitMQ details.

## Scope and exact surfaces

- Audit Horizon `api/nova.py`, `api/glance.py`, admin flavor/image tables,
  forms, views, policies, and tests; record each behavior as reused, adapted,
  already delivered, excluded, or deferred with Apache-2.0 provenance.
- Extend only as required: `src/cps/api/routers/inventory.py`, catalog schemas,
  inventory projections/repository filters, operation response schemas,
  canonical fixtures/checksums/OpenAPI, and their contract/API tests.
- Normalize pagination/sort/filter/detail fields, capability reasons, action
  guards, and safe operation status/error codes for client rendering.
- Contract version remains additive when possible; any breaking shape requires
  an explicit version decision and matching OPS pinned-contract update.

## Acceptance and exclusions

- RED tests first for missing filters/detail/action guards and permission/scope
  leakage; then minimal GREEN and refactor.
- Admin and member responses are scope-correct and expose no credentials,
  provider bodies, image bytes, signed URLs, or unsafe metadata.
- No Django, Horizon UI, novaclient, or glanceclient dependency. Image upload
  bytes and unsafe flavor replace-on-update remain out of scope.
- Focused contract/API tests, full CPS gates, diff/secret scan, and checksum
  parity pass. Runbook: `docs/runbooks/sprint-19-portal-parity.md`.

## Live verification and cleanup

Call list/detail/capabilities through CPS with admin and member identities;
compare provider IDs and material fields with `openstack flavor show/list` and
`openstack image show/list`. This read-only task creates no provider resource.

## Proposed commit

`feat(catalog): define Horizon-parity consumer contracts`
