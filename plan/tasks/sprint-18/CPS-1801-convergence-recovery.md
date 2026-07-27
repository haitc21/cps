# CPS-1801 — Cross-resource convergence and recovery

**Status:** Blocked by CPS-E15..E17
**Points:** 13
**Paired task:** OPS-1801

## Outcome

Every new user-resource workflow has deterministic behavior under duplicate,
restart, timeout, partial mutation, and direct provider drift.

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

