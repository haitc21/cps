# CPS-1802 — Migration, runbook, and real-cloud release acceptance

**Status:** Blocked by CPS-1801
**Points:** 8
**Paired task:** OPS-1802

## Outcome

The CMP user resource increment is operationally releasable.

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
