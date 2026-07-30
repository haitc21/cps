# Volume lifecycle regression runbook

## Purpose

Validate CPS/OPS volume lifecycle behavior end to end without touching the
primary test data volume.

## Variables

```bash
export CPS=http://127.0.0.1:8000
export CONNECTION_ID=019fb108-7ab5-7e0a-9679-9c24f1428275
export INSTANCE_ID=fac1f746-b612-4fd4-ba9f-42567708b9a3
export PROJECT_ID=51006f2625f24f5c891f78839435afe7
export PREFIX=cmp-vl-20260730
```

Use a unique `Idempotency-Key` for every logical request. Never place private
keys or passwords in this file.

## 0. Preflight

```bash
curl -sS "$CPS/health/ready"
curl -sS "$CPS/api/v1/provider-connections/$CONNECTION_ID"
```

Controller:

```bash
source ~/admin-openrc
openstack server show "$INSTANCE_ID"
openstack volume list --project "$PROJECT_ID"
openstack volume snapshot list --project "$PROJECT_ID"
```

Record the primary volume ID and verify it is not a disposable resource.

## 1. Create disposable volume

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volumes" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-volume-create" \
  -d '{
    "operation": "create",
    "required_scope": "PROJECT",
    "name": "cmp-vl-20260730-source",
    "size_gib": 5
  }'
```

Poll the returned `status_url` until terminal. Verify CLI status `available`.
Do not send `project_provider_resource_id` for this project-scoped
connection until VL-04 is fixed and tested.

## 2. Snapshot create

If the volume is attached/in-use, explicitly use force:

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volume-snapshots" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-snapshot-create" \
  -d '{
    "operation": "create",
    "required_scope": "PROJECT",
    "volume_provider_resource_id": "<SOURCE_VOLUME_ID>",
    "name": "cmp-vl-20260730-snapshot",
    "parameters": {"force": true}
  }'
```

Expected: CPS `SUCCEEDED`, CLI snapshot `available`.

## 3. Snapshot update

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volume-snapshots" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-snapshot-update" \
  -d '{
    "operation": "update",
    "provider_resource_id": "<SNAPSHOT_ID>",
    "name": "cmp-vl-20260730-snapshot-updated"
  }'
```

Expected: CPS `SUCCEEDED`; CLI name/description matches. A
`PROVIDER_CONNECTION_NOT_FOUND` response is a failure for VL-01.

## 4. Create volume from snapshot

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volumes" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-volume-from-snapshot" \
  -d '{
    "operation": "create",
    "name": "cmp-vl-20260730-clone",
    "source_snapshot_provider_resource_id": "<SNAPSHOT_ID>"
  }'
```

Expected: CPS `SUCCEEDED`, CLI volume `available`, size not smaller than the
snapshot, and `snapshot_id` equal to `<SNAPSHOT_ID>`.

## 5. Attach clone

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volume-attachments" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-attach" \
  -d '{
    "operation": "attach",
    "volume_provider_resource_id": "<CLONE_VOLUME_ID>",
    "instance_provider_resource_id": "'$INSTANCE_ID'"
  }'
```

Expected: CPS returns a device, CLI shows `in-use`, and `openstack server show`
lists the clone attachment. In the guest, use `lsblk`; do not mount a clone
that contains the same filesystem as an already mounted source.

## 6. Detach clone and verify convergence

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volume-attachments" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-detach" \
  -d '{
    "operation": "detach",
    "volume_provider_resource_id": "<CLONE_VOLUME_ID>",
    "instance_provider_resource_id": "'$INSTANCE_ID'"
  }'
```

Do not accept CPS `SUCCEEDED` alone. Confirm:

```bash
openstack volume show <CLONE_VOLUME_ID>
openstack server show "$INSTANCE_ID"
```

The expected terminal state is volume `available`, no attachment, and no
device in the guest. `detaching` is not converged and must fail or remain
retryable.

## 7. Delete clone

Only after detach is converged:

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volumes" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-volume-delete" \
  -d '{
    "operation": "delete",
    "provider_resource_id": "<CLONE_VOLUME_ID>"
  }'
```

Expected: CPS `SUCCEEDED` and `openstack volume show` returns not found.

## 8. Delete snapshot

```bash
curl -sS -X POST "$CPS/api/v1/provider-connections/$CONNECTION_ID/volume-snapshots" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-snapshot-delete" \
  -d '{
    "operation": "delete",
    "provider_resource_id": "<SNAPSHOT_ID>"
  }'
```

Expected: CPS `SUCCEEDED` and snapshot absent from OpenStack.

## 9. Negative cases

Run and record expected errors:

- resize below current size → validation failure; no provider mutation
- delete attached/detaching volume → conflict/state error
- attach resources from different project → ownership mismatch
- update/delete missing snapshot → idempotent absent or not-found behavior
- replay every request with the same idempotency key → same operation ID

## 10. Final invariant and evidence

```bash
openstack server show "$INSTANCE_ID"
openstack volume show <PRIMARY_VOLUME_ID>
ssh ubuntu@192.168.0.246 'findmnt /data; df -h /data'
```

The primary volume must remain 20 GiB, `in-use`, attached at `/dev/vdb`, and
mounted at `/data`. Record each operation ID, final CPS state, OpenStack state,
provider request ID, and any cleanup blocker.
