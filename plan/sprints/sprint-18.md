# Sprint 18 — CMP user resource release

**Status:** Done (code + lab gates partial)
**Dates:** 2026-07-29
**Capacity:** 21 CPS points
**Sprint Goal:** The complete CMP user resource workflow is releasable across
authorization, migration, restart, redelivery, provider drift, and cleanup.

**Plan:** `../../docs/superpowers/plans/2026-07-27-cmp-user-resource-completion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1801 Cross-resource convergence and recovery | 13 | CPS | OPS-1801 | Done |
| CPS-1802 Migration, runbook, and real-cloud release acceptance | 8 | CPS/OPS | OPS-1802 | Done (runbook + unit gates; migration IT skipped without disposable DB) |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1801](../tasks/sprint-18/CPS-1801-convergence-recovery.md) | Failure matrix and cross-resource reconciliation | CPS-E15..E17 | Done |
| [CPS-1802](../tasks/sprint-18/CPS-1802-release-acceptance.md) | Migration, operations, compatibility, E2E, cleanup | CPS-1801 | Done |
| [CPS-1803](../tasks/sprint-18/CPS-1803-openstack-lab-instance-access-followups.md) | Lab E2E SSH: FIP associate, router+FIP script, hypervisor desync | CPS-1801, OPS-1803 | Done (FIP + hypervisor root cause; SSH gate blocked by libvirt paused-at-spawn after manual recovery) |

## Review evidence

- Contract checksum: pending release tag
- Full quality gates: OPS 324 unit passed; CPS 425 unit passed; ruff clean on changed paths
- Migration lifecycle: `test_migration_lifecycle.py` skipped (requires disposable Postgres fixture in CI)
- Failure matrix: `test_sprint18_recovery_matrix.py`, ack/outbox integration tests in repo
- Real-cloud cleanup ledger: lab `cmp180-*` servers require manual purge (multiple BUILD from retries)
- Runbook: `docs/runbooks/sprint-18-release.md`; lab script `deploy/scripts/sprint-18-openstack-lab-e2e.sh`
- FIP associate: CPS API **SUCCEEDED** (2026-07-29), `provider_service: network`
- Hypervisor: `nova-compute.conf virt_type=kvm`; OpenStack CLI create → ACTIVE with `-accel kvm`
