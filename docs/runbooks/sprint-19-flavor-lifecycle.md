# Sprint 19 flavor lifecycle evidence

## Scope

Paired CPS-1902 / OPS-1902 adds privileged Nova flavor create, delete, access
replacement, and extra-spec patch operations. CPS keeps provider credentials
out of the request and persists an idempotent operation plus outbox message in
one transaction. OPS uses the compute proxy and does not implement mutable
flavor sizing by delete/recreate.

## Automated evidence (2026-08-03)

| Repository | Commands | Result |
| --- | --- | --- |
| CPS | `uv run ruff check …`, `uv run mypy …`, focused contract/API/outbox tests | pass: 46 focused tests |
| CPS | `uv run pytest -q` | pass: 632 passed, 182 skipped |
| OPS | `uv run ruff check …`, `uv run mypy …`, focused contract/registry/handler tests | pass: 58 focused tests |
| OPS | `uv run pytest -q` | pass: 464 passed, 24 skipped |
| Both | `detect-secrets scan --all-files`, `git diff --check` | no reported finding / clean diff check |

The RED tests were observed before implementation: CPS could not import the
typed flavor contract and OPS rejected flavor dispatch as unsupported.

## Live acceptance procedure and observed result

Use a unique disposable name such as `cmp-s19-flavor-<timestamp>` and an
administrator session. Do not record credentials, tokens, authorization
headers, raw provider bodies, or user data.

1. POST the admin CPS flavor endpoint with `Idempotency-Key`; poll its durable
   operation to terminal success.
2. Run `openstack flavor show <provider-id>` and compare ID, name, vCPUs, RAM,
   disk, ephemeral, swap, and public/private status with CPS operation result.
3. Replace access via CPS; compare with `openstack flavor access list`.
4. Patch an additive and a removed extra spec via CPS; compare with
   `openstack flavor extra spec list`.
5. Delete via CPS; poll terminal success, require `openstack flavor show` to
   report not found, then verify CPS refresh tombstones the resource.

Capability validation reached `SUCCEEDED` after rebuilding the stack and
running OPS on host networking because the libvirt controller is not reachable
from the Docker bridge. A disposable create reached OPS but Nova rejected the
stored CPS provider connection with `403 PROVIDER_FORBIDDEN`; the provider CLI
was separately verified to create and immediately delete a disposable flavor,
with absence proved. Full CRUD comparison is blocked on correcting that dev
connection's stored scope/credential, with no CPS-created residue.

## Cleanup ledger

No CPS-created flavor remains. The CLI-only disposable flavor was deleted and
proved absent. Record provider IDs and operation comparisons after the stored
connection is corrected.

## Limitations

The paired handlers are deployed and the CPS→OPS path is reachable; remaining
limitation is the stored lab provider connection's authorization mismatch.
