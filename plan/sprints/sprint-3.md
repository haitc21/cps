# Sprint 3 — Convergent inventory

**Status:** Complete — implementation, regression gates, and live OpenStack acceptance passed
**Goal:** Persist and expose provider-neutral inventory while making full reconciliation safe under batching, reordering, duplication, partial failure, and provider disappearance.
**Canonical design:** `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`
**Canonical executable plan:** `docs/superpowers/plans/2026-07-23-sprint-3-convergent-inventory.md`

## Scope and story backlog

| Story | Points | Status | Acceptance gate |
|---|---:|---|---|
| CPS-301 Typed inventory schema and migrations | 13 | Done | nine typed tables, identity/lifecycle constraints, joins, PostgreSQL 18 migration |
| CPS-302 Inventory sync and batch persistence | 8 | Done | dedupe/checksum/sequence and unsupported-vs-empty semantics |
| CPS-303 Safe full-sync finalization | 13 | Done | deletion only after complete successful required collections |
| CPS-304 Inventory query APIs | 8 | Done | nine list/get endpoints, safe filters, pagination, deleted visibility |
| CPS-305 Manual full sync and targeted refresh APIs | 8 | Done | idempotent operations and safe tombstone behavior |
| OPS-301 Inventory collection coordinator | 8 | Done | bounded collection orchestration and explicit collection outcomes |
| OPS-302 Identity/compute/image collectors and mappers | 13 | Done | typed golden mappings and pagination |
| OPS-303 Network/storage collectors and mappers | 13 | Done | typed relationship-safe mappings and optional service handling |
| OPS-304 Inventory batch publisher | 8 | Done | confirmed deterministic batches and completion semantics |
| OPS-305 Targeted refresh and tombstones | 8 | Done | NotFound tombstones; transient/auth failures never delete |

**CPS total:** 50 points. **OPS total:** 50 points.

## Delivery order

1. CPS-301: schema and migration foundation.
2. CPS-302 + OPS-302/303/304: contract-driven batch ingestion and producer mappings.
3. CPS-303: full-sync state machine and finalization safety.
4. CPS-304: query projections and pagination.
5. CPS-305 + OPS-301/305: manual workflows and targeted refresh.
6. Cross-service synthetic integration, then real OpenStack inventory acceptance.

VM lifecycle, scheduler/recovery epic, and deferred integrations remain out of scope.

## Definition of Done

- Every story has RED/GREEN evidence, focused tests, affected-suite tests, and review evidence.
- CPS canonical contracts are pinned into OPS before producer/consumer behavior is merged.
- PostgreSQL 18 migration upgrade and schema parity pass from a clean database.
- Duplicate, out-of-order, checksum conflict, incomplete sync, unsupported collection, timeout, auth failure, and restart paths are tested.
- No provider SDK object, credential, token, private material, or `user_data` enters inventory or logs.
- Full CPS/OPS gates and non-secret real OpenStack inventory acceptance pass before closure.

## Current evidence

- 2026-07-23: Sprint 3 backlog and executable plan created.
- 2026-07-23 CPS-301: added nine typed inventory tables and instance relationship tables, common identity/lifecycle/version/audit fields, named constraints and indexes, and Alembic revision `20260723_0003`.
- 2026-07-23 CPS-301 verification: metadata/unit/persistence/contract tests `113 passed`; PostgreSQL 18 migration lifecycle/catalog/parity `57 passed`; Ruff, mypy, and `git diff --check` pass.
- 2026-07-23 CPS-301 review: no provider SDK or secret-bearing fields introduced; `provider_attributes` is the only provider extension field and remains JSONB/versioned by contract work still pending in CPS-302.
- 2026-07-23 CPS-302/303: canonical batch contract, idempotent persistence, sequence/checksum validation, explicit unsupported collections, and guarded full-sync tombstone reconciliation implemented; migration `20260723_0004` plus integration/schema gates pass.
- 2026-07-23 CPS-304/305: list/get projections, full sync and targeted refresh operations, deterministic idempotency, lifecycle filtering, migration `20260723_0005`, and explicit DELETED tombstones implemented.
- 2026-07-23 OPS-301..305: nine provider collectors, safe mappers, deterministic chunk publisher, optional-service classification, targeted `get` refresh, and NotFound tombstones implemented; OPS contract pin regenerated.
- 2026-07-23 regression gates: CPS `465 passed, 60 skipped`, OPS `326 passed, 2 skipped`; Ruff, mypy, and diff checks pass; CPS PostgreSQL migration/catalog/parity/inventory integration `58 passed`.
- 2026-07-23 live acceptance: full OpenStack inventory operation `SUCCEEDED` with nine collection batches (volume `SKIPPED_UNSUPPORTED`), query APIs return inventory projections, targeted existing-resource refresh `SUCCEEDED`, and targeted NotFound refresh persisted `DELETED` with operation `SUCCEEDED`.
