# Volume lifecycle hardening plan

Date: 2026-07-30

## Goal

Make CPS/OPS volume lifecycle operations truthful, convergent, and safely
testable against the OpenStack lab:

```text
create → snapshot → clone-from-snapshot → attach → resize → guest-resize
→ detach → delete volume → delete snapshot
```

The operation may report `SUCCEEDED` only after the provider reaches the
requested terminal state. Provider errors must preserve actionable category,
resource ID, service, request ID, and retryability.

## Live defects to fix

| ID | Evidence | Required outcome |
|---|---|---|
| VL-01 | Snapshot update/delete returns `PROVIDER_CONNECTION_NOT_FOUND` before an operation is created | Snapshot update/delete resolve the existing provider connection and resource correctly |
| VL-02 | Detach returns CPS `SUCCEEDED`, while Cinder remains `detaching` and the guest still sees the device | Detach waits for provider convergence; timeout is `FAILED`/retryable with the attachment state |
| VL-03 | Delete of an attached/detaching volume becomes generic `PROVIDER_INTERNAL_ERROR` | Return a specific conflict/state error, never claim deletion; preserve provider request ID |
| VL-04 | Create volume with explicit `project_provider_resource_id` fails; omitting it succeeds on project-scoped connection | Normalize project ownership parameters for scoped credentials or reject them with a clear validation error |
| VL-05 | Resize operation succeeds but CPS result resource still reports old size (`10`) while Cinder is `20` | Refresh the volume after extend and return the authoritative size/status |
| VL-06 | Snapshot create of an in-use volume requires `parameters.force=true` | Document and validate force semantics; return a clear error when force is required |
| VL-07 | Instance action/reboot route can return `PROVIDER_CONNECTION_NOT_FOUND` for the valid project connection | Reproduce with a clean CPS-created instance and fix connection/resource lookup before using it in recovery runbooks |
| VL-08 | Failed create operations can leave provider-side ACTIVE/ERROR servers | Reconcile side effects by operation marker and make terminal failure include the provider resource ID and cleanup/recovery state |

## Ownership and implementation order

Codex remains planner/reviewer. Cursor Composer worker implements one scoped
change at a time. No worker commits or pushes.

### Phase 1 — Contracts and connection/resource resolution

1. Trace CPS snapshot update/delete service path and identify why the valid
   connection ID becomes `PROVIDER_CONNECTION_NOT_FOUND`.
2. Add contract tests for update/delete with the same project connection and
   provider snapshot ID.
3. Add project-scope tests for volume create with and without explicit project
   ownership fields.
4. Define a stable error mapping for `attached`, `detaching`, `available`, and
   `not-found` provider states.

### Phase 2 — OPS provider convergence

1. Add a bounded waiter for volume status transitions.
2. After attach, wait for `in-use` and verify the server attachment/device.
3. After detach, wait for `available` and no server attachment.
4. After resize, refresh the volume and return the new size.
5. For delete, preflight attachment state and map provider conflict to a
   deterministic CPS error.
6. Preserve idempotency: replaying a completed request must not create a
   second volume, snapshot, or attachment.

### Phase 3 — Snapshot lifecycle

1. Support snapshot create from an in-use volume only when `force=true` is
   explicit, or return a validation error explaining the requirement.
2. Fix snapshot update/delete connection resolution.
3. Wait for snapshot `available` after create and `deleted`/not-found after
   delete.
4. Test clone-from-snapshot only after source snapshot is `available`.

### Phase 4 — Recovery and instance actions

1. Reproduce `instance action` lookup failure with a clean operation.
2. Make failed instance create reconcile ACTIVE/ERROR side effects using the
   operation marker.
3. Ensure delete/recovery paths can remove managed keypairs, orphan FIPs, and
   failed provider resources without deleting user resources.

## Required automated tests

### CPS

- Snapshot update/delete route and service tests.
- Volume ownership normalization tests.
- Idempotency tests for volume, snapshot, and attachment operations.
- State-transition tests for terminal provider errors.
- API contract tests asserting operation status URLs and error payloads.

### OPS

- Volume create with project-scoped connection.
- Resize returns refreshed `size` and `status`.
- Attach waits for `in-use` and exposes device.
- Detach waits for `available`; timeout remains retryable.
- Delete attached/detaching volume returns conflict/state error.
- Snapshot force-create, update, delete, and clone-from-snapshot.
- Exact ownership mismatch and no cross-project mutation.

Required gates for every worker change:

```text
pytest focused tests
pytest full suite
ruff check src tests
mypy src
```

## Live acceptance criteria

1. Create a disposable volume with a unique name and no explicit project field
   on the project-scoped connection.
2. Snapshot it with `force=true`; CPS and CLI both show `available`.
3. Update snapshot name/description; CPS and CLI agree.
4. Create a disposable volume from that snapshot; verify source snapshot ID.
5. Attach clone; CPS returns device and CLI shows `in-use`.
6. Detach clone; CPS does not finish until CLI shows `available`.
7. Delete clone; CLI shows it absent.
8. Delete snapshot; CLI shows it absent.
9. Verify the primary `dev-cmp1-data` remains 20 GiB, attached at `/data`.
10. Record every operation ID, request ID, provider state, and cleanup result.

## Safety rules

- Use a disposable prefix such as `cmp-vl-20260730-`.
- Never delete the primary `dev-cmp1-data` volume or the `dev-cmp1` instance in
  this regression run.
- Never force-reset provider state unless the runbook explicitly records the
  attachment ID, reason, command, and post-recovery verification.
- Do not mount a cloned snapshot filesystem on the same guest while the source
  filesystem is mounted.
- Do not commit or push worker changes until Codex review and all gates pass.
