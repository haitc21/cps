# CPS-1801 — Cross-resource convergence and recovery

**Status:** Done
**Active backlog:** No — the automated recovery matrix and existing live
resource evidence satisfy this story.
**Points:** 13
**Paired task:** OPS-1801

## Outcome

Every new user-resource workflow has deterministic behavior under duplicate,
restart, timeout, partial mutation, and direct provider drift.

The Sprint 18 release matrix excludes the superseded console feature and covers
all currently delivered storage, identity, instance, catalog, and network
flows.

## Failure matrix

- command duplicate before/after provider mutation;
- terminal publish failure and redelivery;
- CPS/OPS restart with an in-flight operation;
- provider timeout, 401/403/404/409/429/5xx;
- late result after CPS timeout;
- partial attachment/resize/snapshot relationship mutation;
- direct provider update/delete;
- DLQ replay after correcting an external condition.

## Done when

Automated evidence covers volume, attachment, snapshot, keypair, resize,
rebuild, catalog policy, and network guardrails without unsafe inferred
deletion. The superseded console feature is explicitly outside this matrix.

## Verification evidence

| Failure mode / resource | Evidence |
|---|---|
| Duplicate command and operation identity | `tests/unit/application/test_sprint18_recovery_matrix.py`, `test_volume_operations.py` |
| Terminal redelivery and late result | `tests/integration/messaging/test_inbox_dedupe.py`, including crash-after-commit and late-completed-event cases |
| Worker restart / in-flight delivery | CPS and OPS messaging shutdown/redelivery integration suites; `docs/runbooks/sprint-5-recovery.md` |
| Timeout and deterministic terminal transition | `tests/unit/application/test_recovery.py`; OPS retry/DLQ and provider-error suites |
| Volume attachment and snapshot partial state | CPS `test_volume_snapshot_operations.py`; OPS `test_volume_operations.py` and `test_snapshot_operations.py` |
| Keypair replay and convergent deletion | OPS `test_keypair_operations.py`; Sprint 16 live acceptance |
| Resize/rebuild retry after provider mutation | OPS `test_instance_action.py`; Sprint 17 live acceptance |
| Direct provider drift / safe tombstone | Sprint 3 targeted-refresh tests and live existing-resource/NotFound refresh evidence |
| Catalog and network policy drift | `test_curated_catalog_policy.py`, `test_network_guardrails.py`, and OPS `test_network_operations.py` |
| Real-cloud storage lifecycle and cleanup | `docs/runbooks/live-cps-volume-snapshot-regression-20260731.md` |

The release-level migration rehearsal and release-tag checksum are tracked by
CPS/OPS-1802, not by this convergence story. Console access is superseded and
remains excluded; TMS and physical-infrastructure acceptance are also outside
this task.
