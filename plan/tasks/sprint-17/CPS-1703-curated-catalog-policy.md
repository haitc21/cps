# CPS-1703 — Admin-curated resource catalog policy

**Status:** Ready for policy decision
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

## Required tests

- Approved/global/shared/project-visible combinations.
- Removed approval blocks new use without deleting existing resources.
- Stale/missing catalog entries fail closed.
- Cross-provider IDs and request-supplied approval fields cannot bypass policy.

## Done when

Catalog policy is documented, authorized, queryable, and enforced at every
consumer operation.

