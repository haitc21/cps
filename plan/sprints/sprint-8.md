# Sprint 8 — Identity lifecycle, role assignments, and quotas

**Status:** Complete for internal-network provisioning target  
**Dates:** 2026-07-24 to 2026-08-07  
**Capacity:** 50 combined points  
**Sprint Goal:** Manage disposable OpenStack identity resources, role assignments,
and project quotas through replay-safe CPS/OPS operations with verified cleanup.

**Canonical design:**
`docs/superpowers/specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-801 Domain/project lifecycle APIs | 13 | CPS | OPS-801 | Done |
| CPS-802 Role and assignment inventory/API | 8 | CPS | OPS-802 | Done |
| CPS-803 Project quota inventory/API | 8 | CPS | OPS-803 | Done |
| CPS-804 Identity real-cloud acceptance | 8 | CPS/OPS | OPS-801..803 | Deferred |
| OPS-801 Domain/project handlers | 5 | OPS | CPS-801 | Done |
| OPS-802 Role assignment handlers | 5 | OPS | CPS-802 | Done |
| OPS-803 Quota collectors/handlers | 5 | OPS | CPS-803 | Done |

## Delivery tasks

- [x] Confirm Sprint 7 contracts and scope capabilities are available.
- [x] Define lifecycle, assignment, and quota command/event contracts.
- [x] Add migrations and typed identity/role/quota inventory models.
- [x] Implement idempotent domain/project create/update/disable/delete.
- [x] Implement role assignment ensure/revoke with scope validation.
- [x] Implement quota read/update with unlimited and partial-service semantics.
- [x] Pin CPS contracts in OPS and validate checksums.
- [x] Add redelivery, replay, dependency-conflict, and already-absent tests.
- [ ] Run disposable OpenStack lifecycle and cleanup acceptance.
- [x] Run Definition of Done quality gates and update evidence.

## Acceptance

- Lifecycle operations require compatible connection scope and return durable terminal evidence.
- Domain/project ownership and dependency conflicts are deterministic.
- Role assignments never persist principal secrets and ensure/revoke are idempotent.
- Quota reads/updates normalize unlimited values and preserve partial-service outcomes.
- Duplicate commands and redeliveries produce one durable result.
- Real-cloud disposable resources are cleaned up and no manual provider mutation is required.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Provider catalog endpoints are not routable from Compose | OPS | Preflight endpoint reachability and use disposable acceptance only after correction | Open |
| Keystone policy differs for domain/project administration | OPS | Capability-gate every mutation and report explicit reasons | Open |
| Quota APIs differ by service/version | OPS | Normalize service-specific responses and retain partial outcomes | Open |
| No domain/system-scoped disposable credential | CPS/OPS | Keep mutation scope-gated until a dedicated credential is provisioned | Open |

## Review evidence

- Demo scenario: CPS emits idempotent identity/role/quota operations; OPS validates scope, rejects secrets, and normalizes provider results.
- Test/migration commands and results: CPS `485 passed, 193 skipped`; OPS `355 passed, 24 skipped`; CPS DB integration `146 passed`; Alembic `20260724_0007` upgrade passed.
- Contract checksum: resource-operation pin remains byte-identical; identity commands map to the pinned generic envelope.
- Real-cloud lifecycle/cleanup result: deferred; not required for the internal-network VM provisioning target.
- Known limitations: public floating-IP acceptance and administrative identity lifecycle remain optional follow-up work.

## Retrospective actions

- Keep: explicit scope gating and normalized terminal states.
- Improve: provider policy and endpoint reachability preflight.
- One measurable action for next sprint: add an internal-network SSH connectivity acceptance using the private address returned in `access.ssh.hosts`.
