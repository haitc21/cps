# CPS-1504 — Storage vertical acceptance

**Status:** Done
**Points:** 5
**Depends on:** CPS-1501..1503, OPS-1501..1503

## Outcome

The Sprint 15 storage slice is proven against disposable OpenStack resources.

## Scenario

Create volume, refresh, attach, restart/redeliver, detach, extend, refresh,
delete, and verify tombstone plus provider cleanup.

## Gates

- CPS/OPS contract checksums match.
- Unit, contract, integration, migration, typing, lint, and secret scan pass.
- Provider service/version/capability evidence is recorded.
- Every created resource ID and cleanup result is recorded without secrets.

Acceptance evidence: disposable OpenStack volume/server resources were created,
attached, detached, resized, and deleted through CPS/OPS; operation polling
returned `SUCCEEDED`; replay returned the same operation ID; malformed requests
returned `422`; cleanup verification returned empty all-project volume/server
lists. CPS and OPS suites, lint, and Compose health checks are green.
