# Sprint 18 release runbook

## Scope

This runbook covers the CMP user-resource release path: inventory, instance,
network, volume, snapshot, attachment, keypair, catalog policy, and cleanup.
Console access is deferred and is not part of the release gate.

## Preflight

1. Confirm the CPS and OPS worktrees are clean and the deployed images identify
   the intended commit.
2. Confirm `GET /health/live` and `GET /health/ready` return success for CPS
   and OPS.
3. Confirm both workers consume their queues and no unexpected DLQ messages
   exist.
4. Record the OpenStack service/capability report before creating resources.

## Recovery matrix

For each disposable resource prefix, exercise the operation in these cases:

- duplicate request before and after provider mutation;
- CPS/OPS restart while the command is in flight;
- provider timeout and late terminal result;
- terminal event redelivery;
- direct provider update/delete followed by inventory refresh;
- dependency-ordered delete and a second idempotent delete.

The expected result is one deterministic terminal CPS state, no duplicate
provider resource, and no unsafe inferred deletion from an incomplete sync.

## Migration gate

Run the migration image against a disposable PostgreSQL database. Verify the
empty-schema upgrade, current-head restart, and rollback rehearsal before
touching a release database. Never run migration rollback against production
without an approved backup and change window.

## Cleanup ledger

Record every provider ID as it is created. Delete in dependency order:

1. floating-IP associations and floating IPs;
2. volume attachments;
3. instances;
4. snapshots and volumes;
5. ports, router interfaces, routers, subnets, and tenant networks;
6. imported keypairs and the disposable project.

Close the scenario only when OpenStack lists and CPS inventory (including
deleted/tombstone checks) show no resource belonging to the disposable prefix.
