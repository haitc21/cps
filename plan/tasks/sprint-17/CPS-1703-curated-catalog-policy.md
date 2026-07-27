# CPS-1703 — Admin-curated resource catalog policy

**Status:** In progress — tag policy selected
**Points:** 8
**Depends on:** CPS-304, CPS-1202, CPS-1203
**Paired task:** OPS-1703

## Outcome

Users select only administrator-approved images, flavors, availability zones,
volume types, and external networks.

## Change set

- Approve one policy source: provider metadata/tag convention or explicit CPS
  allow-list persisted by a CMP administrator.
- Add typed catalog projections and workspace-safe list/get filters.
- Validate every catalog reference when creating/rebuilding/resizing instances,
  creating volumes, or allocating floating IPs.
- Expose no workspace-user mutation route for catalog resources.
- Discover and persist provider UUIDs through inventory; never hardcode them.

The first delivery uses the provider metadata/tag convention
`cmp-catalog-approved=true`. OPS normalizes Glance properties and OpenStack
resource tags into `catalog_approved`; CPS exposes only approved, live image,
flavor, and network inventory through a read-only catalog endpoint. Volume-type
and availability-zone projections remain explicit follow-up inventory work.

## Required tests

- Approved/global/shared/project-visible combinations.
- Removed approval blocks new use without deleting existing resources.
- Stale/missing catalog entries fail closed.
- Cross-provider IDs and request-supplied approval fields cannot bypass policy.

## Done when

Catalog policy is documented, authorized, queryable, and enforced at every
consumer operation.

## Review evidence

- OPS mapper tests cover approved and rejected tags/properties; CPS catalog
  contract tests and full CPS/OPS suites pass.
- `GET /api/v1/provider-connections/{id}/catalog?resource_type=image` was
  exercised against the running Compose API and returned only the curated
  projection (empty when the provider inventory has no approved item).
- A project-scoped inventory sync against the disposable acceptance project
  was rejected by OpenStack authorization before mutation, confirming the
  provider scope is not bypassed by catalog queries.
