# CPS-1302 — Reconcile stale VM-create operations

## Goal

Ensure every stale VM-create operation reaches a deterministic terminal state
by asking OPS to inspect provider truth; CPS must not access OpenStack directly.

## Scope

- Select nonterminal VM-create operations whose convergence deadline has
  elapsed, using indexed bounded batches.
- Publish an idempotent reconcile command containing the operation, provider
  connection, and known provider resource identity.
- Fall back to the immutable `cmp_operation_id` provider marker only when no
  server ID was persisted.
- Apply bounded retry, jitter, and a final operation deadline.
- Map reconciled provider states to CPS terminal outcomes while preserving
  immutable event history and late-result evidence.
- Emit stage, attempt, age, and outcome metrics without secret material.

## Acceptance

- Provider `ACTIVE` or `SHUTOFF` converges the create operation to `SUCCEEDED`.
- Provider `ERROR` converges it to `FAILED` with a normalized safe error.
- Confirmed absence after the final deadline converges it to `TIMED_OUT`.
- Temporary CPS/OPS/provider unavailability retries without creating another
  Nova server or an unbounded message loop.
- Concurrent scheduler executions create one logical reconciliation attempt.
- Restarting CPS during reconciliation does not lose or duplicate terminal
  state.

## Verification

- Unit tests for stale selection, state mapping, retry, and terminal races.
- PostgreSQL integration test for concurrent claims and outbox atomicity.
- RabbitMQ restart/redelivery test.
- Real OpenStack test that recovers an `ACTIVE` VM from a stuck 20-percent
  operation.
