# CPS-1802 — Migration, runbook, and real-cloud release acceptance

**Status:** Done
**Active backlog:** No
**Points:** 8
**Paired task:** OPS-1802

## Outcome

The CMP user resource increment is operationally releasable.

The operational procedure is pinned in
`docs/runbooks/sprint-18-release.md`; final release status depends on the
CPS-1801 recovery matrix and disposable real-cloud run.

## Required gates

- Clean PostgreSQL 18 install and supported current-head upgrade/downgrade.
- CPS/OPS contract checksum parity, full unit/contract/integration suites,
  formatting, linting, typing, secret scan, and Compose smoke.
- Per-resource metrics, stale-operation/DLQ procedures, migration rollback, and
  dependency-ordered cleanup runbook.
- Recorded OpenStack service versions/capabilities and unsupported operations.
- Full release scenario from curated selection through VM/network/storage/key
  lifecycle and verified zero-residual cleanup.

## Done when

All Must gates pass, no critical/high defect remains, and every disposable
provider resource is confirmed removed.

## 2026-07-31 verification

- Disposable PostgreSQL 18 migration lifecycle now passes empty-to-head,
  downgrade-to-base, and re-upgrade-to-head (`6 passed`). The rehearsal exposed
  and fixed stale expected-table coverage for `availability_zones` and
  `volume_types`.
- CPS/OPS contract manifests are byte-identical at SHA-256
  `b46f6bf5fa5913f5561c4cf53a9f2adae3d0327a951f02d0ebe7f151328841bc`;
  CPS contract tests pass `101`, OPS contract tests pass `83`.
- Current Compose CPS/OPS APIs and dependencies are healthy; both readiness
  endpoints return `status: ok`.
- CPS inventory has zero active `cmp180-*` instances, networks, subnets,
  routers, volumes, snapshots, or keypairs.
- The lab smoke script now fails on non-success terminal operations and does
  not silently treat a missing `NETWORK_ID` as a complete run. The runbook uses
  the required base + OpenStack-lab Compose files.
- Enabling the previously skipped full CPS database integration suite exposed
  stale pre-head `credentials` table and repository expectations. They now use
  provider-owned credential schema/API truth; the complete database integration
  suite passes (`131 passed`).
- CPS live RabbitMQ messaging integration passes (`45 passed`), including
  terminal delivery, retry/DLQ, crash recovery, and worker reconnect. The
  reconnect test now waits for the restored consumer and sends a
  contract-valid `WAITING_PROVIDER` progress event.
- Final default gate: Ruff and mypy pass; pytest reports `568 passed, 178
  skipped`.

- Provider-authoritative cleanup was verified through the controller:
  `cmp180-*` server, network, subnet, router, volume, snapshot, and keypair
  queries all returned zero rows.
- A second KVM compute was cloned with its disk at
  `/data/libvirt/images/compute02.qcow2`. Both `compute01` and `compute02`
  registered `enabled/up` with Nova and their OVS agents were healthy.
- Cold migration `compute01 → compute02` and reverse migration
  `compute02 → compute01` both completed and were confirmed. `cmp-dev` was
  restored `ACTIVE` on `compute01`; TCP/22 succeeded on both hosts.
