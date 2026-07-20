# CPS AI Review Checklists

## Story kickoff

- [ ] Active sprint and story ID identified.
- [ ] Acceptance criterion is testable and in scope.
- [ ] Design and relevant backlog entry read.
- [ ] Worktree status checked; unrelated changes protected.
- [ ] CodeGraph queried before code search when indexed.
- [ ] Cross-service contract dependency identified.

## API and contract

- [ ] Canonical schema changed before implementation.
- [ ] Compatibility/schema-version decision explicit.
- [ ] Valid, invalid, and unknown-version fixtures tested.
- [ ] Correlation/idempotency fields preserved.
- [ ] Secret fields excluded/redacted.
- [ ] OPS pinned-copy update identified.

## Domain and persistence

- [ ] Business rule is framework-independent.
- [ ] Transaction boundary is explicit.
- [ ] Database constraints enforce key invariants.
- [ ] Alembic migration applies cleanly on PostgreSQL 18.
- [ ] Duplicate/concurrent behavior tested.
- [ ] Soft-delete and incomplete-sync safety preserved.

## Messaging

- [ ] Publisher confirm and ack order are correct.
- [ ] Handler is idempotent on duplicate/redelivery.
- [ ] Retry class and maximum are explicit.
- [ ] Timeout/restart/out-of-order behavior tested.
- [ ] Poison message reaches DLQ.
- [ ] Payload has no credential/token/user data.

## Security

- [ ] Synthetic test credentials only.
- [ ] Logs/errors/traces verified redacted.
- [ ] Public and internal routes remain separated.
- [ ] No secret in Git diff, fixtures, snapshots, or operation payload.
- [ ] Dependency addition reviewed and locked.

## Completion

- [ ] New test failed first for expected reason.
- [ ] Focused and affected suites pass.
- [ ] Full repository quality gates pass.
- [ ] `rtk git diff --check` passes.
- [ ] Docs/contracts/migration notes updated.
- [ ] Sprint Backlog evidence and status updated.
- [ ] Completion report cites fresh command results.
