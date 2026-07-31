# Live CPS volume lifecycle hardening — 2026-07-30

## Scope and rule

This runbook records validation of the CPS/OPS lifecycle fixes. Resource
mutations in this run were sent through CPS API only. OpenStack CLI was used
only afterward to inspect provider state; it was not used to create, attach,
detach, delete, or repair the test resource.

Connection: `019fb108-7ab5-7e0a-9679-9c24f1428275` (`ttcntt`)

## Automated gates

- CPS: `543 passed, 181 skipped`; Ruff and mypy passed.
- OPS: `437 passed, 24 skipped`; Ruff and mypy passed.
- Focused regression tests: `17 passed` for volume/snapshot lifecycle.

## VL-01 — snapshot update after delayed inventory projection

Existing CPS-created snapshot:

- Snapshot: `648f4ad1-9815-43e0-897b-67521d4ecbbe`
- Original create operation: `a53d17b7-4f6f-59a8-957d-b33855a2a470`

CPS request:

```http
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/volume-snapshots
Idempotency-Key: live-vl01-update-20260730
```

```json
{
  "operation": "update",
  "provider_resource_id": "648f4ad1-9815-43e0-897b-67521d4ecbbe",
  "name": "dev-cmp1-data-snapshot-updated"
}
```

Result: operation `44c873ac-3061-5b2b-afad-ad945640215d` reached `SUCCEEDED`.
The controller CLI read-back showed the same snapshot ID with the new name and
status `available`. This confirms CPS ownership evidence is retained when the
inventory projection temporarily lags; arbitrary foreign provider IDs remain
rejected by unit tests.

## VL-02 — detach must not report success before Cinder convergence

Disposable volume created through CPS:

- Create operation: `6efc44aa-e405-5171-906e-e58f15add330`
- Volume: `cf687c65-66a0-4aba-a089-46fa5c8c6d92`
- Instance: `fac1f746-b612-4fd4-ba9f-42567708b9a3`

CPS attach operation `fd5f2c44-55d5-51ff-8275-733a67cdbb48` reached
`SUCCEEDED` and returned device `/dev/vdd`.

CPS detach operation `00b39e94-287a-50ca-bfc5-16b57da8de32` was submitted via
the volume-attachments endpoint. It remained `QUEUED` while the controller
CLI read-back showed Cinder status `detaching` with the attachment still
present. This is the expected safe behavior of the new bounded waiter; the
operation is **not marked complete**. The provider/backend convergence remains
blocked and requires a later CPS-only retry after Cinder leaves `detaching`.

## VL-03 — delete of transitioning volume must fail closed

CPS delete request for the same volume produced operation
`59765299-01f9-569e-9814-79727901a8cc`, which reached `FAILED` with:

```json
{
  "code": "INVALID_RESOURCE_STATE",
  "category": "CONFLICT",
  "details": {
    "provider_reason": "volume_attached_or_transitioning",
    "provider_status": "detaching",
    "provider_resource_id": "cf687c65-66a0-4aba-a089-46fa5c8c6d92"
  }
}
```

No CLI delete or reset-state operation was performed. The provider resource
therefore remains as a cleanup blocker rather than being falsely reported as
deleted.

## Current conclusion

- VL-01: verified through CPS API and provider read-back.
- VL-03: verified fail-closed through CPS API and provider read-back.
- VL-02: implementation behavior verified against a real `detaching` state,
  but terminal detach convergence is still pending; do not mark the task Done.

## Cleanup ledger

The disposable volume remains intentionally recorded as a blocker because its
Cinder attachment is still `detaching`. Cleanup must be retried through CPS
API after provider convergence. Direct controller CLI repair is prohibited by
this validation rule.

## Controller/compute log diagnosis

Read-only inspection was performed at `2026-07-30T07:47:29Z`.

Provider services were reported `enabled/up` for `nova-compute` on `compute01`,
`cinder-volume` on `compute01@lvm`, `nova-conductor`, and `cinder-scheduler`.
The resource was nevertheless still `detaching` with the attachment present.

Relevant logs:

- `/var/log/nova/nova-compute.log` on `compute01`:
  - `07:32:50` Nova started detaching the volume and attempted `/dev/vdd`.
  - Libvirt reported the device was still present in the persistent domain
    configuration, although it was removed from the live domain configuration.
  - `07:32:51` attachment deletion failed with HTTP 409:
    `ConflictNovaUsingAttachment: Detach volume from instance ... using the
    Compute API`.
- `/var/log/apache2/cinder_error.log` on `controller`, correlated by CPS
  provider request `req-e287bb2f-3785-4dd1-8cbb-2cfad0ecaa89`:
  - `07:38:22.339` Cinder logged:
    `Unable to detach volume. Volume status must be 'in-use' and attach_status
    must be 'attached' to detach.`
  - `07:38:22.353` the Cinder action returned HTTP 400.

The CPS operation failed at `07:38:22`, well before its `timeout_at` of
`07:47:48`. Therefore the observed failure is not a CPS waiter timeout. It is
an OpenStack provider/integration failure: Nova's libvirt detach partially
completed, but the Nova/Cinder attachment state remained inconsistent, leaving
Cinder in `detaching` and rejecting the subsequent detach action. The current
OPS error is a generic `PROVIDER_INTERNAL_ERROR`; the underlying provider
status is HTTP 400 after the earlier HTTP 409 conflict.

## VL-04 — detach convergence retry regression

OPS now retries Nova `delete_volume_attachment` up to three times with a
two-second interval for transient `ConflictException`. Non-conflict errors
remain immediate failures; no direct Cinder attachment deletion or reset-state
fallback was added.

Automated verification in OPS: `439 passed, 24 skipped`, Ruff passed, mypy
passed, and focused volume tests `8 passed`. The updated OPS image was rebuilt
and restarted locally.

A fresh disposable volume was exercised through CPS API only:

- Create `a7cf181b-6047-5ea7-aadf-7180b29439a2`: `SUCCEEDED`; volume
  `0a0e4962-47eb-4b83-a1f6-feac4006d163`.
- Attach `a5aeb7bb-de5b-5c07-904b-ac62ec46264a`: `SUCCEEDED`, `/dev/vde`.
- Detach `f308533f-4281-5a3d-ad38-d83dca157853`: `FAILED`.
- CPS retry `b8ce24cc-c0e1-5ba5-97a7-6a3e397e8efe`: `FAILED`.

Controller CLI read-back after both CPS requests showed the new volume still
`detaching`, with attachment `2cbc69ad-317b-4fb8-a208-519317c60fca` present on
`dev-cmp1`; the server remained `ACTIVE` and listed the volume. This reproduces
the failure on a newly created volume, so the remaining issue is provider /
backend convergence, not stale CPS inventory or the old volume. VL-04 is **not
Done**; provider remediation is required before CPS-only detach/delete can be
verified successfully.

For the fresh volume, compute01 logged the same provider failure:

- `08:07:20.635`: libvirt could not remove `/dev/vde` from the persistent
  domain config.
- `08:07:20.741`: libvirt reported successful removal from the live domain.
- `08:07:21.220`: Nova/Cinder returned `ConflictNovaUsingAttachment` HTTP 409
  for attachment `2cbc69ad-317b-4fb8-a208-519317c60fca`, request ID
  `req-839e647e-7b76-4a55-beeb-7d187680593c`.

This confirms the retry reaches the provider, but cannot repair the underlying
persistent libvirt/Nova/Cinder state mismatch.

## VL-05 — OpenStack 2025.2 post-upgrade acceptance (2026-07-30)

### Controller CLI pre-check (read-only)

The pre-check was run on controller `192.168.122.253` with OpenStack CLI.
No OpenStack CLI mutation was performed.

- `openstack --version`: `openstack 8.2.0`
- Keystone, Nova, Neutron, Glance, Placement, and Cinder services were
  present in `openstack service list`.
- Nova scheduler/conductor and compute service were `enabled/up`.
- Cinder scheduler and `compute01@lvm` volume service were `enabled/up`.
- All Neutron agents were `Alive: :-)`.
- Existing server read-back: `test-instance`, UUID
  `dbb63eb7-72c4-426a-aaa3-6b116a4ae936`, state `ACTIVE`.
- `openstack volume list --all-projects`: empty.

### CPS API validation

A provider and system-scoped provider connection were created through CPS API:

- Provider: `019fb259-cc0a-7db1-bd92-155662c67b8d`
- Connection: `019fb259-cc0b-726a-b98a-22dcc24734b7`

The first validation used `http://controller:5000/v3` and failed:

- Operation `019fb25a-eb68-7433-b833-25e7c875bdbe`: `FAILED`,
  `PROVIDER_INTERNAL_ERROR`.
- OPS log showed `keystoneauth` could not discover identity versions from
  `http://controller:5000/v3`.

The provider endpoint was then corrected through CPS `PATCH /api/v1/providers`
to the controller address and validation was retried:

- `019fb25b-a492-7cbb-863f-13814e997953`: `FAILED`,
  `PROVIDER_INTERNAL_ERROR` for `192.168.122.253:5000`.
- `019fb25d-70a2-797f-9432-22ea2a43b61c`: `QUEUED` at the time of the
  network workaround attempt; no resource mutation was started.
- The endpoint was restored through CPS API to `http://controller:5000/v3`.

Read-only connectivity evidence explains the failure: host curl to
`http://controller:5000/v3` returned Keystone `v3.14`, while a socket test
from `cmp-ops-worker-1` to both `controller:5000` and
`192.168.122.253:5000` returned `ConnectionRefusedError(111)`. The Docker
Compose network cannot reach the libvirt controller network, and its current
`controller:host-gateway` mapping points at an unusable Docker bridge address.

Therefore the 2025.2 CPS API runbook is **BLOCKED before provider validation**.
No volume was created, attached, detached, resized, or deleted in this run;
there is no CPS evidence to claim volume lifecycle compatibility after the
upgrade. This is a local Docker-to-controller network/configuration blocker,
not evidence of an OpenStack 2025.2 API regression and not a CPS timeout.

### Required unblock

Make the controller endpoint reachable from the OPS worker network (for
example, correct the Compose `extra_hosts`/routing or place the worker on a
network with access to `192.168.122.0/24`), then rerun this section. Only after
`connection.validate` succeeds may the CPS-only volume create/attach/detach/
delete lifecycle be marked passed.

## VL-06 — Network fixed; Cinder catalog compatibility remains blocked

The Docker-to-controller routing blocker from VL-05 was resolved externally:

- `cmp-ops-worker-1` reached `http://192.168.122.253:5000/v3` with HTTP 200.
- `cmp-ops-worker-1` reached `http://controller:5000/v3` with HTTP 200.
- The `controller` host mapping now resolves to `192.168.122.253`.
- Forwarding through `virbr0` was allowed on the Docker host.

CPS validation was rerun successfully:

- Operation `019fb26c-aea2-73ba-b2a3-e88e9f116a4b`: `SUCCEEDED`.
- CPS reported Keystone `v3.14`, Nova microversion `2.100`, Glance `2.17`,
  and Neutron as available.

CPS inventory sync also succeeded:

- Operation `019fb26c-e42d-7390-9d11-8840706b3487`: `SUCCEEDED`.
- Collections: `flavor`, `image`, `network`, `volume`, `instance`.

A project-scoped CPS connection was created and validated for the existing
OpenStack project `myproject` (`b362943314264bccbe617ce386b7ae61`):

- Connection: `019fb26d-6faa-7a0f-a80d-a782f651ec8a`.
- Validation operation: `019fb26d-7f0e-76c6-8d8d-9e58fe14af7f`, `SUCCEEDED`.

Both CPS-only volume-create attempts failed before a Cinder request was
recorded:

- `61499df8-48d7-50cf-85a8-9d5a254085a5`: `FAILED`, with explicit
  `project_provider_resource_id`.
- `e84c21fc-3892-5768-828b-ff2441fba1cb`: `FAILED`, using the project-scoped
  connection without an explicit project ID.

The CPS validation capability document marked `block_storage.available=true`
but returned no block-storage endpoint or version. Controller CLI read-only
inspection shows the Cinder service registered only as type `volumev3`, while
the OPS OpenStackSDK block-storage service resolves the standard type
`block-storage`. Cinder access logs contain no corresponding create request,
confirming this is endpoint resolution before the provider HTTP call, not a
Cinder backend timeout.

VL-06 is therefore **BLOCKED on the OpenStack Keystone catalog**. Add a
`block-storage` service type with public/internal/admin endpoints pointing to
the existing Cinder v3 URL, or update the existing Cinder service type after
checking client compatibility. Do not remove the existing `volumev3` service
until CPS volume operations pass. After the catalog is corrected, rerun the
CPS-only create/attach/detach/delete lifecycle; no OpenStack CLI mutation was
performed by this run.

## VL-07 — Cinder create payload and project ownership (2026-07-30)

After the Docker route and Keystone `block-storage` service type were fixed,
the CPS provider reached Cinder successfully.

The project-scoped connection for `myproject` authenticated with
`project_name=myproject` but was rejected by Keystone as `Unauthorized`,
because the configured `admin` user is not authorized in that project. A
separate CPS provider/connection was created with an `admin` project token:

- Provider: `019fb277-4fd2-78fd-abe6-f9868564aac1`
- Connection: `019fb277-630a-72cb-ade9-37207fe94e9e`
- Validation operation: `019fb277-72ec-7dc2-aa02-106520a70f10`, `SUCCEEDED`.

The following CPS-only create attempt included the target project ID and
reached Cinder, but Cinder returned HTTP 400:

- Operation: `cc40dd67-448e-56df-b188-04e05d46c069`
- Provider request ID: `req-1ba11588-833a-4a8c-8c14-064322280fcc`
- Cinder log: `POST /v3/7a6434d271c9464091d86d82c377de78/volumes` → HTTP 400.

The same CPS API create operation without `project_provider_resource_id`
succeeded:

- Operation: `95256401-773f-541f-892b-d70b7d7cb23f`, `SUCCEEDED`.
- Temporary volume: `52b7042b-38f0-407c-852f-a6ecbed2dc9b`.
- Cinder reported the volume project as `admin` (`7a6434d271c9464091d86d82c377de78`).

The temporary volume was deleted through CPS API:

- Operation: `a8799dd2-eb5c-5ccd-91c5-9af40e6581e0`, `SUCCEEDED`.
- Controller CLI read-back found no remaining volume with that ID.

This proves the OpenStack 2025.2 Cinder endpoint and basic CPS volume create
path work. The remaining blocker is project ownership: OPS currently sends
`project_id` to Cinder when the token is scoped to `admin`, and Cinder rejects
that cross-project create with HTTP 400. The test instance belongs to
`myproject`, so the admin-owned temporary volume could not be attached to it.
VL-07 is **BLOCKED** until either a credential with a role in `myproject` is
provided to CPS, or OPS/CPS implements a supported project-scoped ownership
flow. No volume remains from this test.
