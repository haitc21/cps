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
