# Live CPS remaining volume lifecycle tests — 2026-07-30

## Scope

Tested the remaining volume APIs against project connection
`019fb108-7ab5-7e0a-9679-9c24f1428275` in project `ttcntt`:

- snapshot create/update/delete
- create volume from snapshot
- attach/detach derived volume
- delete derived volume

The primary volume `dev-cmp1-data` (`eeadb58d-a055-4c59-bbed-dfb778ecd0f1`)
was preserved. The instance is `dev-cmp1`
(`fac1f746-b612-4fd4-ba9f-42567708b9a3`).

## Preflight

- CPS readiness: `ok`; database and RabbitMQ: `up`
- Provider connection: `VALID`
- Instance: `ACTIVE`
- Primary volume: 20 GiB, `in-use`, `/dev/vdb`, mounted at `/data`

## Snapshot create

Normal snapshot create while the volume was `in-use` failed:

- Operation: `cf7b5d74-533e-504f-876a-ee312ae6dd6b`
- Result: `FAILED`, `PROVIDER_INTERNAL_ERROR`

Retry without the redundant project field also failed:

- Operation: `a998e5d3-4277-5180-a998-7af3a368a4b5`
- Result: `FAILED`, `PROVIDER_INTERNAL_ERROR`

The API supports `parameters.force`. Using it succeeded:

```json
{
  "operation": "create",
  "volume_provider_resource_id": "eeadb58d-a055-4c59-bbed-dfb778ecd0f1",
  "name": "dev-cmp1-data-snapshot-01",
  "parameters": {"force": true}
}
```

- Operation: `a53d17b7-4f6f-59a8-957d-b33855a2a470`
- Result: `SUCCEEDED`
- Snapshot ID: `648f4ad1-9815-43e0-897b-67521d4ecbbe`
- Snapshot status: `available`
- Snapshot size: 20 GiB

## Snapshot update

The update request was rejected by CPS before creating an operation:

```text
POST .../volume-snapshots
operation: update
provider_resource_id: 648f4ad1-9815-43e0-897b-67521d4ecbbe
```

Result:

```text
PROVIDER_CONNECTION_NOT_FOUND
```

This is an API/service bug to fix. It is not a provider-side snapshot update
result.

## Create volume from snapshot

Request:

```json
{
  "operation": "create",
  "name": "dev-cmp1-from-snapshot",
  "source_snapshot_provider_resource_id":
    "648f4ad1-9815-43e0-897b-67521d4ecbbe"
}
```

- Operation: `86cce44c-56ee-5cae-8084-0907fe4cf208`
- Result: `SUCCEEDED`
- Derived volume ID: `ad7d8c06-6948-4f5d-8ff8-f5c5ae8ac819`
- Size: 20 GiB
- Source snapshot ID: `648f4ad1-9815-43e0-897b-67521d4ecbbe`

## Attach derived volume

- Operation: `4edc6ba1-8de1-583e-9adb-dba73c6ff398`
- Result: `SUCCEEDED`
- Device: `/dev/vdc`

OpenStack CLI and guest verification showed `/dev/vdc` as a 20 GiB ext4
device. It was intentionally not mounted in the guest because it contains the
same filesystem data copied from the primary volume and mounting the same
filesystem concurrently would be unsafe.

## Detach derived volume

- Operation: `bb82fe4b-8a4e-501c-90f7-5a3af5cfc060`
- CPS result: `SUCCEEDED`
- Actual Cinder state: `detaching`

The provider retained the attachment record and the guest continued to show
`/dev/vdc`. This reproduces the existing detach convergence defect observed
with the primary volume. The volume must not be deleted while this state is
present.

## Delete derived volume

Delete was attempted through CPS:

- Operation: `f0314f9c-6c17-5ca3-be51-959b62b283c0`
- Result: `FAILED`, `PROVIDER_INTERNAL_ERROR`

The failure is consistent with the volume still being attached/detaching.

Snapshot delete was also submitted, but CPS rejected it before creating an
operation with `PROVIDER_CONNECTION_NOT_FOUND`, the same CPS-side issue seen
for snapshot update.

## Final provider state after test

The primary volume remains healthy and attached:

- `dev-cmp1-data`: 20 GiB, `in-use`, `/dev/vdb`

The test resources currently require cleanup after the detach convergence bug:

- `dev-cmp1-from-snapshot`: 20 GiB, `detaching`, `/dev/vdc`
- `dev-cmp1-data-snapshot-01`: `available`

No resource was force-deleted, and no primary volume data was removed.

## Conclusions

Passed:

- Snapshot create with `force=true` for an in-use volume
- Create volume from snapshot
- Attach derived volume

Blocked/failed:

- Snapshot update/delete: CPS returns `PROVIDER_CONNECTION_NOT_FOUND`
- Detach: CPS reports success while provider remains `detaching`
- Delete attached/detaching volume: correctly does not complete, but returns a
  generic provider internal error

Recommended fixes are to correct snapshot operation connection resolution,
make detach wait for provider convergence before emitting `SUCCEEDED`, and
improve volume delete error normalization for attached/detaching volumes.
