# Live CPS volume and snapshot regression — 2026-07-31

## Scope

Rerun the disposable volume/snapshot lifecycle after the OpenStack lab was
reinstalled from 2024.1 to 2025.2 and `cmp-dev` networking was restored.

All resource mutations were submitted through CPS. OpenStack CLI and guest SSH
were used only for read-back verification.

- CPS connection: `019fb27f-b6e0-7c98-8c96-2de5c5c8d28c`
- OpenStack project: `ttcntt`
  (`bf4fac71208a4ca7a1f941a1cc7f2bd7`)
- Instance: `cmp-dev`
  (`99e1a41f-c2a8-4776-8d26-87eecd8dc97c`)
- Disposable prefix: `cmp-vl-20260731-101655`

No root disk or existing persistent data was modified.

## Preflight

- CPS readiness: `ok`; PostgreSQL and RabbitMQ: `up`.
- Provider connection: `VALID`.
- `cmp-dev`: `ACTIVE`, no Cinder volume attached before the test.
- `cinder-scheduler`: `enabled/up`.
- `cinder-volume` on `compute01@lvm`: `enabled/up`.
- The project contained no volumes or snapshots before the test.

## Results

### Volume create

- Operation: `d83e981f-5fd7-5a1b-875a-0353c27d3b05`
- Result: `SUCCEEDED`
- Volume: `9527e80a-2110-42e9-8184-2f3146f89f66`
- Name: `cmp-vl-20260731-101655-source`
- Size: 5 GiB
- Provider read-back: `available`, correct `ttcntt` ownership.

This confirms the earlier Cinder catalog and project-scoping blockers are
resolved for the current `ttcntt` project connection.

### Snapshot create

- Operation: `aa44f84e-2855-5368-adf9-99cd37073578`
- Result: `SUCCEEDED`
- Snapshot: `1bc8f6a2-8388-4b31-9036-eb82741ce2e5`
- Size/status: 5 GiB, `available`

The source volume was `available`, so `force=true` was not required.

### Snapshot update

- Operation: `d3047b08-1893-540d-8d8b-22372572cfbd`
- Result: `SUCCEEDED`
- Updated name: `cmp-vl-20260731-101655-snapshot-updated`

The previous `PROVIDER_CONNECTION_NOT_FOUND` defect did not reproduce.

### Create volume from snapshot

- Operation: `a06cafee-2396-54e8-98e2-5abd115cd0b5`
- Result: `SUCCEEDED`
- Clone: `959879e5-bd54-4fb2-8ca1-a4460475ed1a`
- Size/status before attach: 5 GiB, `available`
- `snapshot_id`: `1bc8f6a2-8388-4b31-9036-eb82741ce2e5`

### Attach clone

- Operation: `da675842-3db5-506a-9ced-f4f6c3ef45d2`
- Result: `SUCCEEDED`
- Device: `/dev/vdb`

Cinder reported `in-use`; `lsblk` in `cmp-dev` showed a 5 GiB `vdb`. The
empty disposable disk was not formatted or mounted.

### Initial detach failure

- Operation: `3138e03d-421e-544b-8dc6-3ddc3cea2e3e`
- Final result: `FAILED`
- CPS error: `PROVIDER_INTERNAL_ERROR`
- Provider request:
  `req-d7087211-f1fd-4735-9326-4bcd6f41ce50`

The bounded waiter did not report a false success. It kept the operation
`QUEUED` while Cinder remained `detaching`, then emitted `FAILED`.

Provider state after the attempt:

- The guest no longer showed `/dev/vdb`.
- Libvirt removed `vdb` from the live domain.
- Nova still listed the attachment.
- Cinder remained `detaching` with attachment
  `c83aee5a-74a2-4357-bb69-1f9a2b6dd227`.

Compute log:

```text
Failed to detach device vdb ... from the persistent domain config.
Successfully detached device vdb ... from the live domain config.
ConflictNovaUsingAttachment ... HTTP 409
```

The initial symptom looked like the Nova/libvirt/Cinder persistent-domain
convergence defect recorded on 2026-07-30. Further comparison and provider-log
analysis identified the actual post-upgrade configuration defect below.

### Horizon comparison and root cause

Horizon from the same release calls Nova's server-volume detach API with the
server ID and volume ID. CPS uses the equivalent OpenStackSDK method:

```python
compute.delete_volume_attachment(server_id, volume_id)
```

Therefore the CPS detach implementation was already correct. Bypassing Nova
with Cinder `force-detach` would not match Horizon and would risk leaving
compute/libvirt state behind.

Cinder logged the decisive warning during Nova's attachment-delete request:

```text
A valid token was submitted as a service token, but it was not a valid service token
```

After the OpenStack 2025.2 reinstall:

- the `nova` user had only the `admin` role in the `service` project;
- `[service_user]` was not configured in `nova.conf` on `compute01`;
- Nova consequently did not send a valid service-user token to Cinder;
- Cinder rejected attachment deletion with
  `ConflictNovaUsingAttachment` (HTTP 409).

### Provider remediation

The following provider configuration was applied:

1. Granted the `service` role to user `nova` in project `service`.
2. Configured Nova `[service_user]` on `compute01` with password
   authentication against Keystone and `send_service_user_token = true`.
3. Restarted `nova-compute` and verified it was active.

The original config is retained at:

```text
/etc/nova/nova.conf.bak-service-user-20260731
```

For the already-stuck disposable attachment, both live and inactive libvirt
XML were first verified to contain no `vdb`. Only then was the Cinder state
restored to `in-use/attached`, allowing a new detach request to run through
Nova:

- Recovery detach operation:
  `1aaab78e-cbb1-58be-90b1-70ac2234fbb3`
- Result: `SUCCEEDED`
- Provider result: clone `available`, no attachments

### Fresh attach/detach verification

A new cycle against the same disposable clone, without any state reset,
verified the configuration fix:

- Attach operation: `bf3f4484-c55c-5a22-b108-af6c93dc8586`
- Attach result: `SUCCEEDED`
- Detach operation: `ccee9224-b1f2-5a54-8029-e686f574bcb2`
- Detach result: `SUCCEEDED`
- Final provider result: clone `available`, no attachments

Cinder logs from the verification window contained no invalid-service-token
warning.

### Delete while detaching

- Operation: `579f0cef-6fa8-5c67-8819-8da66ad83ad1`
- Result: `FAILED`
- Error: `INVALID_RESOURCE_STATE`
- Provider status: `detaching`
- Provider reason: `volume_attached_or_transitioning`

The fail-closed behavior is correct. CPS did not force-delete the volume.

### Independent snapshot delete probe

A second disposable snapshot was created and deleted to test snapshot delete
without depending on the stuck clone:

- Create operation: `27967e38-4d36-5a8b-b1c3-93b14464c22a`
- Snapshot: `093a0ba7-ed75-4098-a7ae-91d92d91bf8a`
- Create result: `SUCCEEDED`
- Delete operation: `0216c1fd-aba6-5312-837b-5554c53b4839`
- Delete result: `SUCCEEDED`
- Provider read-back: snapshot absent

The previous snapshot-delete `PROVIDER_CONNECTION_NOT_FOUND` defect did not
reproduce.

## Acceptance summary

| Scenario | Result |
|---|---|
| Volume create in target project | PASS |
| Snapshot create | PASS |
| Snapshot update | PASS |
| Create volume from snapshot | PASS |
| Attach clone | PASS |
| Detach clone provider convergence after remediation | PASS |
| Prevent delete while detaching | PASS |
| Snapshot delete | PASS |

Snapshot lifecycle, connection resolution, and Nova/Cinder detach convergence
all pass after restoring the Nova service-user token configuration required by
OpenStack 2025.2.

## Cleanup ledger

Cleanup was completed through CPS:

| Resource | Delete operation | Result |
|---|---|---|
| Clone volume `959879e5-bd54-4fb2-8ca1-a4460475ed1a` | `248e4e75-8a5f-5dce-9ea8-d7fa92542044` | `SUCCEEDED` |
| Source snapshot `1bc8f6a2-8388-4b31-9036-eb82741ce2e5` | `a652c626-7562-52a0-8780-ab9fcda52018` | `SUCCEEDED` |
| Source volume `9527e80a-2110-42e9-8184-2f3146f89f66` | `c2305f00-f1e2-5011-a041-266fd3ad646c` | `SUCCEEDED` |

Final verification:

- `cmp-dev` is `ACTIVE` and has no attached Cinder volumes.
- The guest has only its root `vda`; `vdb` is absent.
- The `ttcntt` project contains no volumes or snapshots from this run.
- SSH access to `cmp-dev` remains operational.
