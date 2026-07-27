# CPS-1502 — Volume create/update/extend/delete

**Status:** Ready
**Points:** 8
**Depends on:** CPS-1501
**Paired task:** OPS-1502

## Outcome

An authorized workspace user manages a standalone data volume through one
durable, replay-safe operation family.

## Change set

- Add typed create/update/extend/delete requests, schemas, fixtures, routing
  keys, result snapshots, and tombstones.
- Validate project ownership, approved volume type, size bounds, metadata, and
  provider capability before publishing.
- OPS uses Cinder proxy methods, deterministic replay preconditions, bounded
  waiters, and normalized errors.
- Refuse shrink, attached/root delete, and implicit cascade.

## Required tests

- Idempotency-key replay and changed-payload conflict.
- Duplicate delivery before/after provider mutation.
- Timeout, 403/404/409/429/5xx, restart, late result, and absent delete.
- Cross-project and unapproved volume-type denial.
- Create/update/extend/delete inventory convergence.

## Done when

A disposable volume completes the full lifecycle with deterministic operation
history and verified cleanup.

