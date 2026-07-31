# CPS-1202 — Canonical project ownership for tenant resources

**Status:** Done
**Active backlog:** No — canonical project ownership and tenant-resource
projection evidence are complete.
**Points:** 13  
**Depends on:** CPS-1201, CPS-704  
**Paired task:** OPS-1201  
**Design:** `../../../docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`

## Outcome

Every tenant-owned resource can be resolved to one canonical CPS project and
therefore to one TMS organization/workspace without trusting request-supplied
tenant identifiers.

## Change set

### Canonical project

- Add `provider_id`, `org_id`, `workspace_id`, and `ownership_state` to
  `projects`.
- Make OpenStack project identity unique by
  `(provider_id, provider_resource_id)`, independent of collection connection.
- Add a partial unique constraint for
  `(provider_id, org_id, workspace_id)` when workspace is present.
- Treat TMS MongoDB `_id` values as opaque strings.
- Keep `identity_bindings` as workflow state; project rows are the canonical
  resource ownership read model.

### Tenant resource linkage

- Add nullable `project_id` FK and `project_provider_resource_id` to instances,
  volumes, networks, subnets, ports, routers, security groups, security-group
  rules, floating IPs, images, quotas, and snapshot models added in the future.
- Add indexes for project FK and provider project identity.
- Do not add tenant ownership to regions, identity domains, or flavors.
- Keep global/shared resources nullable and classify them explicitly.

### Inventory and operation results

- Normalize owner project from `location.project.id`, `project_id`, then
  `tenant_id`.
- Use project-scoped connection identity only as an explicit fallback.
- Resolve canonical project FK during full sync, targeted refresh, and
  operation-result persistence.
- Process/project inventory early enough to resolve dependent collections.
- Persist unresolved provider project identity and reconcile it when the project
  appears later.
- Never erase `org_id`, `workspace_id`, or `ownership_state` during inventory
  upsert/tombstone.
- Project a `READY` binding into the canonical project row transactionally.

### Query behavior

- Add repository filters by internal project, organization, and workspace.
- Use provider identity when matching OpenStack project IDs.
- Exclude unresolved/unbound resources from workspace-user queries.
- Preserve CMP-admin visibility for reconciliation.

## Implementation order

1. Add failing migration/model/index tests.
2. Migrate and canonicalize project uniqueness.
3. Add project linkage columns to tenant resource models.
4. Update normalized inventory contracts with project owner identity.
5. Update repository ingestion and operation-result persistence.
6. Add binding-to-project projection and unresolved ownership reconciler.
7. Add tenant-safe repository/API filters.
8. Update OPS fixtures/checksum through OPS-1201.

## Required tests

- Same OpenStack project collected through two connections resolves one
  canonical project.
- Identical project strings in two providers never collide.
- Managed project persists deterministic test `org_id` and `workspace_id`.
- Inventory refresh preserves ownership.
- Resource observed before project becomes resolved after reconciliation.
- Unresolved, unbound, and disabled ownership denies workspace queries.
- Shared/public resources remain nullable and follow global policy.
- Every tenant model has required FK and indexes.
- Cross-workspace and cross-provider list/get leakage tests fail closed.

## Verification

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

## Done when

- Tenant resources resolve with one indexed ownership lookup.
- Statistics can group reliably by organization/workspace through canonical
  project FK.
- Inventory and operation writes preserve provider and CMP ownership.
- No workspace API can return an unresolved or foreign resource.

## Out of scope

- Usage/billing fact tables in BMS.
- TMS/LMS schema or endpoint changes.
- Automatic ownership adoption by matching display names.
