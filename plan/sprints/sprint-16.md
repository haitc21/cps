# Sprint 16 — CMP user snapshots and SSH access

**Status:** In progress
**Dates:** TBD at Sprint Planning
**Capacity:** 21 CPS points
**Sprint Goal:** An authorized workspace user can snapshot/clone project
storage and manage SSH public keypairs without CPS handling private keys.

**Plan:** `../../docs/superpowers/plans/2026-07-27-cmp-user-resource-completion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1601 Volume snapshot lifecycle | 8 | CPS | OPS-1601 | Done |
| CPS-1602 Project-owned keypair lifecycle | 8 | CPS | OPS-1602 | Ready after contract refinement |
| CPS-1603 Snapshot/keypair acceptance | 5 | CPS/OPS | OPS-1601..1602 | Blocked |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1601](../tasks/sprint-16/CPS-1601-snapshot-lifecycle.md) | Snapshot inventory/create/update/delete and clone input | CPS-1501..1503 | Done |
| [CPS-1602](../tasks/sprint-16/CPS-1602-keypair-lifecycle.md) | Public-key-only keypair list/import/delete | CPS-1202, CPS-1203 | Ready |
| [CPS-1603](../tasks/sprint-16/CPS-1603-snapshot-keypair-acceptance.md) | Snapshot clone and SSH VM acceptance | CPS-1601..1602 | Blocked |

## Execution sequence

1. Pin snapshot and public-key-only keypair contracts.
2. Add snapshot persistence, reconciliation, waiter, and tombstones.
3. Add keypair inventory and import/delete operations.
4. Create a volume from snapshot and boot a VM with the imported keypair.
5. Prove cross-project denial, redaction, replay, and cleanup.

## Acceptance

- Snapshot ownership always follows its source volume/project.
- Snapshot delete refuses active dependencies and absent delete is idempotent.
- Keypair input accepts public material only; no private key field exists.
- Duplicate imports converge by project/name/fingerprint without silent adoption.
- Real-cloud clone and SSH access pass with verified cleanup.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Snapshot becomes available slowly | OPS | Bounded waiter plus reconciliation command | Open |
| Provider exposes generated private key | OPS | Reject/drop private material before serialization | Open |
| Keypair names collide in a project | CPS/OPS | Fingerprint precondition and explicit conflict | Open |

## Review evidence

- Contract/redaction evidence: typed create/update/delete contracts, project
  ownership checks, deterministic operation/message IDs, and replay coverage.
- Snapshot waiter/recovery: bounded Cinder availability waiter, idempotent
  delete handling, inventory sync, and deleted-resource tombstones.
- SSH acceptance:
- Cleanup: temporary Cinder volumes/snapshots and the temporary OpenStack
  project were removed; direct OpenStack lists were empty.
