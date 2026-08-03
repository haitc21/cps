# CPS-1907 — Flavor and image administration parity closure

**Status:** Planned  
**Points:** 13  
**Paired task:** OPS-1907  
**Depends on:** CPS-1906

## Testable outcome

An authorized administrator completes the safe Horizon-equivalent flavor and
image journeys through CPS while every mutation remains durable, replay-safe,
capability-gated, and visible through CPS operations.

## Flavor acceptance

- List/detail/filter; create/delete; public/private access replacement; extra
  spec add/change/remove; deterministic conflicts and action availability.
- Preserve core sizing immutability. Do not copy Horizon's PATCH behavior that
  deletes and recreates a flavor.

## Image acceptance

- List/detail/filter by name/status/visibility/owner/format/minimums/tags;
  create metadata plus allowlisted HTTPS import; metadata/property add/change/
  remove; visibility/protection; member grant/revoke; deactivate/reactivate;
  delete and snapshot-derived inventory convergence.
- Never transport bytes or credential-bearing/signed/private URLs. URL import
  remains unavailable when capability or source policy is absent.

## Files, tests, and security

- Likely surfaces: API schemas/routers, operation application service,
  contracts/fixtures/checksums, inventory projections, authorization, and
  focused contract/API/application/messaging tests. Planner must use CodeGraph
  to replace this list with exact symbols before implementation.
- RED tests cover RBAC/scope, protected/status guards, invalid metadata/URL,
  duplicate/replay/restart, timeout, late result, provider conflict, and
  unsupported capability before production changes.
- Threat-model SSRF, metadata injection, access escalation, destructive delete,
  cross-project disclosure, and secret logging. Unresolved Critical/High blocks.

## Verification, cleanup, and commit

For one disposable flavor and image, poll every CPS mutation to terminal and
compare IDs/material fields after each step with OpenStack CLI. Exercise one
negative, replay, and worker-restart path; delete task-created resources and
prove absence. Update `docs/runbooks/sprint-19-portal-parity.md`.

Proposed commit: `feat(catalog): close flavor and image admin parity gaps`
