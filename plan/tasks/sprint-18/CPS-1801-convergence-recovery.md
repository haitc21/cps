# CPS-1801 — Cross-resource convergence and recovery

**Status:** In progress — FIP associate + idempotency fixed 2026-07-29
**Points:** 13
**Paired task:** OPS-1801

## Outcome

Every new user-resource workflow has deterministic behavior under duplicate,
restart, timeout, partial mutation, and direct provider drift.

The Sprint 18 release matrix excludes the deferred console feature and covers
all currently delivered storage, identity, instance, catalog, and network
flows.

## Failure matrix

- command duplicate before/after provider mutation;
- terminal publish failure and redelivery;
- CPS/OPS restart with an in-flight operation;
- provider timeout, 401/403/404/409/429/5xx;
- late result after CPS timeout;
- partial attachment/resize/snapshot relationship mutation;
- direct provider update/delete;
- DLQ replay after correcting an external condition.

## Done when

Automated evidence covers volume, attachment, snapshot, keypair, resize,
rebuild, console boundary, catalog policy, and network guardrails without
unsafe inferred deletion.
