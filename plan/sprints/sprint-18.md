# Sprint 18 — CMP user resource release

**Status:** In progress
**Dates:** TBD at Sprint Planning
**Capacity:** 21 CPS points
**Sprint Goal:** The complete CMP user resource workflow is releasable across
authorization, migration, restart, redelivery, provider drift, and cleanup.

**Plan:** `../../docs/superpowers/plans/2026-07-27-cmp-user-resource-completion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1801 Cross-resource convergence and recovery | 13 | CPS | OPS-1801 | In progress |
| CPS-1802 Migration, runbook, and real-cloud release acceptance | 8 | CPS/OPS | OPS-1802 | In progress — gate preparation |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1801](../tasks/sprint-18/CPS-1801-convergence-recovery.md) | Failure matrix and cross-resource reconciliation | CPS-E15..E17 | In progress |
| [CPS-1802](../tasks/sprint-18/CPS-1802-release-acceptance.md) | Migration, operations, compatibility, E2E, cleanup | CPS-1801 | In progress |
| [CPS-1803](../tasks/sprint-18/CPS-1803-openstack-lab-instance-access-followups.md) | Lab E2E SSH: FIP associate, router+FIP script, hypervisor desync | CPS-1801, OPS-1803 | Open — deferred |

## Execution sequence

1. Freeze CPS contracts and pin OPS checksums.
2. Run the cross-resource duplicate/restart/timeout/drift matrix.
3. Verify clean and current-release migration lifecycle.
4. Run full authorization, secret, and operational gates.
5. Execute the disposable real-cloud release scenario.
6. Verify no residual OpenStack resource remains.

## Acceptance

- Every nonterminal mutation converges or reaches a deterministic terminal state.
- Direct provider drift is observed without unsafe inferred deletion.
- Clean install and supported upgrade/downgrade preserve ownership/history.
- Cross-workspace reads and mutations remain denied during all recovery paths.
- Real-cloud scenario completes with capability report and verified cleanup.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Cleanup failure leaves billable resources | Team | Dependency-ordered cleanup ledger and manual runbook | Open |
| Provider capabilities vary | OPS | Recorded capability matrix and explicit skips | Open |
| Recovery matrix exceeds sprint capacity | Product | Must scenarios first; split compatibility breadth if needed | Open |
| OpenStack lab: QEMU tcg crash on nested compute; CPS FIP associate fails; E2E lacks router+FIP/SSH gate | CPS/OPS/Lab | [CPS-1803](../tasks/sprint-18/CPS-1803-openstack-lab-instance-access-followups.md), [OPS-1803](../../ops/plan/tasks/sprint-18/OPS-1803-nested-lab-hypervisor-fip-fixes.md) | Open |

## Review evidence

- Contract checksum:
- Full quality gates:
- Migration lifecycle:
- Failure matrix:
- Real-cloud cleanup ledger:
- Runbook: `docs/runbooks/sprint-18-release.md` added; acceptance evidence is
  pending the recovery matrix and final disposable run.
