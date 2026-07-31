# CPS-1703 — Admin-curated resource catalog policy

**Status:** Done
**Active backlog:** no — implemented and covered by CPS/OPS quality gates
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
flavor, network, volume-type, and availability-zone inventory through a
read-only catalog endpoint. Cinder volume types use the same marker in
`extra_specs`. Nova availability zones inherit the marker from host-aggregate
metadata, because Nova availability-zone records do not expose tags or
metadata directly.

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
- Typed availability-zone and volume-type inventory, migration, collection,
  targeted refresh, catalog filtering, and create-reference validation are
  covered. CPS rejects unapproved AZ references for instance creation and
  unapproved volume-type/AZ references for volume creation before publication.
- Reviewer removed a stale router short-circuit that still returned empty
  results for the two new catalog types and added an API regression test.
- Final quality gates: CPS 557 passed/181 skipped; OPS 450 passed/24 skipped;
  Ruff and MyPy pass in both repositories.
- `GET /api/v1/provider-connections/{id}/catalog?resource_type=image` was
  exercised against the running Compose API and returned only the curated
  projection (empty when the provider inventory has no approved item).
- Migration `20260731_0016` was applied to the Compose PostgreSQL database and
  verified as the single Alembic head. A disposable PostgreSQL database passed
  full upgrade, downgrade to `20260727_0015`, and re-upgrade.
- Live inventory operation `019fb676-18d7-7825-b8a9-5a75f55c25d8`
  synchronized both collections. Catalog queries returned approved AZ `nova`
  and Cinder volume type `__DEFAULT__`, including their discovered provider
  identifiers and `catalog_approved=true`.
