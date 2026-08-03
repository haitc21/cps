# CPS-1902 Flavor lifecycle

- [x] RED: add typed contract, API-route, and durable-outbox/idempotency tests; observe missing contract/handler failures.
- [x] GREEN: add admin `POST /provider-connections/{id}/flavors`, typed immutable create/delete/access/spec contracts, capability gate, deterministic operation/outbox IDs.
- [x] Refactor: format imports and retain existing operation/outbox transaction boundary.
- [x] Review/security: self-review rejects mutable sizing, cross-mode idempotency, unsafe public-access inputs, and secrets in parameters.
- [ ] Live: create/access/spec/delete via CPS and compare Nova CLI (paired with OPS-1902).
- [ ] Cleanup/runbook: record only redacted command evidence and zero-residual check in `docs/runbooks/sprint-19-flavor-lifecycle.md`.
- [ ] Commit: task-scoped CPS-1902 commit after independent review and live evidence.

Blast radius: `OperationApplicationService`, command routing allow-list, admin operation router, CPS↔OPS typed contract. Version remains `1.0`; no database migration or OpenStack SDK dependency in CPS.
