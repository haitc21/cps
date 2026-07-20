# CPS Scrum Delivery Plan

**Plan date:** 2026-07-17
**Design source:** `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`
**Cadence:** two-week sprints, adjustable by team capacity
**Estimation:** Fibonacci story points; points express relative complexity, not elapsed time

## Product goal

Deliver CPS as the durable, provider-neutral control plane that manages OpenStack provider connections, credentials, inventory, and VM operations through OPS. Each sprint must produce an integrated, testable increment and preserve the future Keycloak, TMS, LMS, and VMware extension boundaries.

## Working agreement

- The approved design is authoritative. A scope or contract change requires a design update before implementation.
- CPS owns canonical OpenAPI, JSON Schema, and golden contract fixtures.
- Every story starts with failing automated tests and ends with evidence that acceptance criteria pass.
- `main` remains releasable. Work uses short-lived branches and reviewable vertical slices.
- Database changes use Alembic migrations and include upgrade verification from an empty PostgreSQL 18 database.
- No credentials, OpenStack tokens, `user_data`, or real customer payloads enter Git, logs, fixtures, or test reports.
- Cross-service contract changes merge in CPS first, then update the pinned OPS copy in the same sprint.

## Definition of Ready

A story is ready when:

- Business outcome and acceptance criteria are testable.
- API/message/schema impact is identified.
- Dependencies and owner are known.
- Security/redaction and failure behavior are stated.
- Required OpenStack test data or infrastructure is available.
- Story is small enough to complete within one sprint; otherwise it is split.

## Definition of Done

A story is done when:

- Acceptance criteria pass in automated tests.
- Unit tests cover domain branches and error paths.
- Integration/contract tests are added where boundaries change.
- Formatting, linting, typing, tests, migration checks, and secret scanning pass.
- API/message documentation and examples match implementation.
- Logs and errors are verified not to expose secrets.
- Operational configuration and health behavior are documented.
- Code is reviewed and merged; no unresolved critical/high defect remains.

## Sprint roadmap

| Sprint | Goal | CPS increment | Cross-service exit criterion |
|---|---|---|---|
| 0 | Reproducible engineering foundation | Python 3.12 project, CI, config, health, DB/Rabbit infrastructure | CPS and OPS build/test from clean checkout with pinned locks |
| 1 | Stable contracts and durable operation core | Common schemas, operation state machine, DB foundations, inbox/outbox skeleton | Golden command/event fixtures validate in both repos |
| 2 | First end-to-end provider workflow | Provider/credential/connection API and async validation operation | Real OpenStack connection validates and capabilities persist |
| 3 | Convergent inventory | Typed inventory DB/API, full-sync batching/finalization, targeted refresh | All scoped resources sync from real OpenStack without unsafe deletion |
| 4 | VM lifecycle | Create/detail/start/stop/reboot/delete APIs and operation handling | Both boot modes and lifecycle actions pass end-to-end |
| 5 | Recovery and release readiness | Scheduler, timeout reconciliation, DLQ operations, observability, restart tests | Acceptance suite passes across restart/redelivery/direct drift scenarios |

## Scrum events and artifacts

- Sprint Planning: select only ready stories up to observed capacity; confirm OPS dependencies.
- Daily Scrum: focus on sprint-goal risk, blocked contracts, migrations, and environment issues.
- Backlog Refinement: at least once per sprint; re-evaluate every 13-point story and split it when team capacity or uncertainty prevents completion within one sprint.
- Sprint Review: demonstrate a running vertical workflow, not isolated modules.
- Retrospective: record one measurable process improvement for the next sprint.
- Product Backlog: `plan/product-backlog.md`.
- Sprint Backlog: created at sprint planning as `plan/sprints/sprint-<n>.md` from selected story IDs.
- Increment evidence: commands, test reports, API examples, migration result, and relevant screenshots/log excerpts without secrets.

## Release gates

The first product increment is release-candidate quality only after:

1. All Must stories are Done.
2. CPS/OPS contract checksums and golden fixtures match.
3. PostgreSQL migrations pass on a clean database and supported upgrade path.
4. Duplicate, redelivery, partial-sync, timeout, and restart tests pass.
5. Real OpenStack acceptance scenarios pass.
6. No critical/high security issue or secret leak remains.
