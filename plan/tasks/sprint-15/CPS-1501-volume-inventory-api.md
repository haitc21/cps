# CPS-1501 — Project-owned volume inventory and API

**Status:** Ready
**Points:** 8
**Depends on:** CPS-1202, CPS-1203
**Paired task:** OPS-1501

## Outcome

Volumes are typed, project-owned inventory resources that workspace users can
query without cross-tenant leakage.

## Change set

- Extend canonical inventory contracts with volume type ID, size, status,
  bootable/root flags, encrypted flag, metadata, availability zone, and bounded
  attachment summaries.
- Add or migrate indexed ownership and provider-identity columns.
- Add full-sync and targeted-refresh ingestion, tombstones, list/get filters,
  and authorization checks.
- Keep volume types read-only, admin-curated catalog references.

## Required tests

- Full and partial sync, targeted not-found, reappearance, and duplicate batch.
- Same provider ID in different providers never collides.
- Unresolved/foreign project volume is denied to workspace users.
- Root and attachment fields survive refresh.
- Clean/current-head upgrade and downgrade pass.

## Done when

Contract parity, migration lifecycle, repository/API tests, authorization, and
real-cloud read-only inventory evidence pass.

