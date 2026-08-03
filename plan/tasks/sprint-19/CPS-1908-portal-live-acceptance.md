# CPS-1908 — API and provider live parity acceptance

**Status:** Planned  
**Points:** 8  
**Paired task:** OPS-1908  
**Depends on:** CPS-1907

## Testable outcome

The admin/member CPS API journeys agree with CPS durable state and the same
OpenStack resources, including recovery and zero-residual cleanup.

## Acceptance matrix

- Admin: flavor/image list, detail, filters and all supported safe actions;
  permission denial and capability-unavailable actions are explicit.
- Member: only approved/scope-visible compatible image/flavor choices appear
  for create, rebuild, resize, and volume-from-image, with rejection reasons.
- API clients submit idempotency keys and poll operations to terminal without
  receiving credentials or raw provider errors.
- Automated CPS contract/integration suites pass, followed by full CPS/OPS gates.

## Live test and cleanup

Drive real CPS API calls against directly debugged CPS/OPS, capture redacted
API evidence, and independently compare provider IDs, sizes, access,
metadata, visibility, status, and protection with OpenStack CLI. Include replay,
OPS restart, failure normalization, client retry, and authorization denial.
Delete only task-created resources and verify absence via CLI and reconciliation.

## Evidence and proposed commit

Publish `docs/runbooks/sprint-19-portal-parity.md` with commands, comparisons,
test summaries, review closure, cleanup ledger, limitations, and both repository
hashes after separately authorized commits.

Proposed commit: `docs(sprint-19): publish flavor image API acceptance`
