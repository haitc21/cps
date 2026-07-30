# Live CPS volume create and attach test — `dev-cmp1`

Date: 2026-07-30 (Asia/Bangkok)

## Final result

Successful. A new 10 GiB Cinder volume was created through CPS API, attached
to `dev-cmp1` through CPS API, verified with OpenStack CLI, formatted as ext4,
and mounted persistently at `/data` inside the instance.

Final values:

- CPS project connection:
  `019fb108-7ab5-7e0a-9679-9c24f1428275`
- Instance: `dev-cmp1`
- Instance ID: `fac1f746-b612-4fd4-ba9f-42567708b9a3`
- Volume: `dev-cmp1-data`
- Volume ID: `eeadb58d-a055-4c59-bbed-dfb778ecd0f1`
- Size: `10 GiB`
- OpenStack device: `/dev/vdb`
- Guest mount: `/data`
- Filesystem UUID: `21efb786-33f8-4315-8c28-dfc72f16d697`

No image, flavor, default domain, default project, or shared provider network
was modified.

## 1. Preflight

CPS readiness was healthy:

```text
GET /health/ready
{"status":"ok","checks":{"database":{"status":"up"},"rabbitmq":{"status":"up"}}}
```

The project connection was `VALID`. OpenStack CLI confirmed `dev-cmp1` was
`ACTIVE` with fixed address `192.168.0.246` and no attached volumes before
the test.

## 2. First create attempt and correction

The first request included `project_provider_resource_id` in the volume
payload:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volumes
Idempotency-Key: cmp-live-dev-cmp1-data-volume-create-20260730
```

Operation: `c0647b02-148e-56ef-9bb1-b4ec3f7dd271`

Result: `FAILED`, `PROVIDER_INTERNAL_ERROR`, provider service
`block_storage`; no volume was present in OpenStack.

The retry omitted the redundant project field because the CPS connection is
already project-scoped. This is the request that succeeded:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volumes
Idempotency-Key: cmp-live-dev-cmp1-data-volume-create-retry-20260730
```

Body:

```json
{
  "operation": "create",
  "required_scope": "PROJECT",
  "name": "dev-cmp1-data",
  "size_gib": 10,
  "metadata": {
    "purpose": "live-cps-volume-test",
    "instance": "dev-cmp1"
  }
}
```

Operation: `dde81ea9-f715-5ec7-b133-8e923b5d7117`

Result: `SUCCEEDED`; provider volume ID:
`eeadb58d-a055-4c59-bbed-dfb778ecd0f1`.

## 3. OpenStack CLI verification before attach

Controller command:

```bash
source ~/admin-openrc
openstack volume show eeadb58d-a055-4c59-bbed-dfb778ecd0f1
```

Observed state:

```text
name: dev-cmp1-data
size: 10
status: available
tenant_id: 51006f2625f24f5c891f78839435afe7
type: __DEFAULT__
```

## 4. Attach through CPS API

Request:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volume-attachments
Idempotency-Key: cmp-live-dev-cmp1-data-volume-attach-20260730
```

Body:

```json
{
  "operation": "attach",
  "required_scope": "PROJECT",
  "volume_provider_resource_id": "eeadb58d-a055-4c59-bbed-dfb778ecd0f1",
  "instance_provider_resource_id": "fac1f746-b612-4fd4-ba9f-42567708b9a3",
  "project_provider_resource_id": "51006f2625f24f5c891f78839435afe7"
}
```

Operation: `7b3c3f80-2c8f-58e3-b389-e8abf6f9fa91`

Result: `SUCCEEDED`; CPS result reported device `/dev/vdb`.

## 5. OpenStack CLI verification after attach

The controller showed:

```text
volume status: in-use
attachment server_id: fac1f746-b612-4fd4-ba9f-42567708b9a3
attachment device: /dev/vdb
attachment_id: 00014bcf-6e62-4069-b321-cfcaf65ee151
```

## 6. Format and mount inside the instance

The new, empty device was formatted with ext4 and mounted persistently:

```bash
sudo mkfs.ext4 -F /dev/vdb
sudo mkdir -p /data
sudo sh -c 'printf "UUID=<volume-uuid> /data ext4 defaults,nofail 0 2\n" >> /etc/fstab'
sudo mount /data
sudo chown ubuntu:ubuntu /data
```

The final guest verification was:

```text
TARGET SOURCE   FSTYPE OPTIONS
/data  /dev/vdb ext4   rw,relatime

Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb        9.8G   24K  9.3G   1% /data

VOLUME_MOUNT_OK
```

The filesystem UUID recorded in `/etc/fstab` is
`21efb786-33f8-4315-8c28-dfc72f16d697`.

## 7. Resize from 10 GiB to 20 GiB

Resize request through CPS:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volumes
Idempotency-Key: cmp-live-dev-cmp1-data-volume-resize-20g-20260730
```

Body:

```json
{
  "operation": "resize",
  "required_scope": "PROJECT",
  "provider_resource_id": "eeadb58d-a055-4c59-bbed-dfb778ecd0f1",
  "size_gib": 20
}
```

Operation: `8a2dfca9-3fc9-594d-8be1-4a3d96654db0`; CPS result:
`SUCCEEDED`.

OpenStack CLI then confirmed:

```text
size: 20
status: in-use
device: /dev/vdb
```

The first CPS result payload still displayed the old resource size (`10`) even
though the provider had already resized it. The authoritative follow-up CLI
read showed `size: 20`.

## 8. Refresh attachment and filesystem after resize

The guest initially continued to see `/dev/vdb` as 10 GiB. An online virtio
rescan was unavailable in this guest. A CPS detach operation
`7bb7b3d7-c40f-5e07-b4be-7aa5c237acf4` returned `SUCCEEDED`, but the provider
attachment remained stuck in `detaching`; the first CPS reattach operation
`7844c890-1aae-5849-8bf6-90ec5a82246a` consequently failed.

For recovery, the stale provider attachment record was cleared on the
controller using the documented Cinder reset-state troubleshooting path. The
instance was stopped/started on the controller while recovering the stale
Nova attachment metadata. No volume data was deleted. The final attach was
then performed again through CPS:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volume-attachments
Idempotency-Key: cmp-live-dev-cmp1-data-volume-reattach-recovered-20260730
```

Operation: `8d3b321d-69a9-504b-993a-bb8cb21c3bd6`; result: `SUCCEEDED`;
device: `/dev/vdb`.

The guest filesystem was expanded with:

```bash
sudo resize2fs /dev/vdb
```

Final guest verification:

```text
NAME SIZE FSTYPE MOUNTPOINTS
vdb  20G  ext4   /data

Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb         20G   24K   19G   1% /data

VOLUME_RESIZE_OK
```

Final controller verification:

```text
volume size: 20
volume status: in-use
attachment device: /dev/vdb
server status: ACTIVE
```

## Notes

- Creating a volume with an explicit `project_provider_resource_id` failed in
  this project-scoped lab connection; omitting it succeeded.
- The volume is not configured with `delete_on_termination`; deleting the VM
  will not automatically delete this data volume.
- The attach API adds the block device. Formatting and mounting require a
  separate guest OS step, which was completed here.
- A volume resize changes the Cinder block device first. The guest filesystem
  must also be expanded with the filesystem-appropriate tool (`resize2fs` for
  this ext4 volume).
