# Sprint 19 catalog contracts — live evidence

Date: 2026-08-03

## Scope

CPS-1901 and OPS-1901 catalog contract, inventory projection, mapper, and
capability changes. No image/flavor mutation or provider catalog resource was
created by this acceptance run.

## Verification

- CPS focused/full gates: `626 passed, 182 skipped`; Ruff and mypy passed.
- OPS full gate: `459 passed, 24 skipped`; Ruff and mypy passed.
- CPS and OPS contract validation passed; CPS/OPS/pinned manifests matched.
- Alembic head: `20260801_0017`; Compose upgrade, downgrade to `20260731_0016`,
  and upgrade back to head succeeded. Five catalog indexes were present.
- CPS and OPS readiness endpoints returned `status: ok`.
- Inventory operation `019fc5ae-00e9-74a3-a787-01a124e75584` initially failed
  because the Compose worker could not route to the libvirt network. A retry
  using the temporary host-network worker completed as `SUCCEEDED`; no provider
  mutation was performed by the sync.

## CPS ↔ provider comparison

Provider CLI was run on the controller VM. CPS member catalog was queried with
the same project connection after the successful image/flavor sync.

| Resource | Provider ID | CPS ID | Material fields |
|---|---|---|---|
| ubuntu-24.04 image | `9985f9af-e2a4-42de-8004-55288cd88971` | same | active, public, 665382912 bytes, qcow2, checksum `02ef3db73722173e9371f47448e2e165`, min disk/RAM 0 |
| n1.normal flavor | `98f3201f-97e9-4fbf-8dc3-a3f04354169b` | same | 4096 MiB, 2 vCPU, 40 GiB root disk |
| n1.small flavor | `f29e1fd8-f928-4f11-aca0-b39338ec1f5f` | same | 2048 MiB, 1 vCPU, 20 GiB root disk |

The provider returned null for some flavor defaults in `flavor show`; CPS
normalizes those defaults (`ephemeral=0`, `is_public=true`).

## Cleanup ledger

- Deleted disposable servers `cmp-dev` and `test-instance`.
- Deleted disposable floating IPs `192.168.57.141` and `192.168.57.157`.
- Deleted disposable `cmp-*` keypairs.
- Removed disposable ports where Neutron allowed deletion; retained the router
  interface port belonging to the shared `selfservice` network.
- Marked CPS projections `cmp-dev`, `cmp1704-net`, `cmp1704-subnet`, and
  `cps1701-resize-disposable` as `DELETED`.
- Preserved shared base images, flavors, provider/selfservice networks, and
  router infrastructure.

## Limitations and follow-up

- The Compose-to-libvirt route remains an environment limitation. The live
  sync required a temporary host-network OPS worker; the normal Compose worker
  was restored afterward.
- The Valkey cluster-init helper exits non-zero but does not affect CPS/OPS
  readiness or this acceptance path.
- Git commit/push hashes are intentionally omitted until explicitly authorized
  for the current commit action.
