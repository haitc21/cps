# Sprint 3 executable plan — convergent inventory

## Planning decisions

- CPS remains the only inventory source of truth; OPS owns collection and mapping only.
- Each typed resource uses `(provider_connection_id, provider_resource_id)` as identity.
- Inventory is soft-deleted and reappearance reactivates the same CPS UUID.
- A full sync may delete missing rows only after every supported required collection closes successfully and all batch integrity checks pass.
- `SKIPPED_UNSUPPORTED` is distinct from an empty successful collection.
- Batch messages are immutable and deduplicated by `(sync_id, resource_type, sequence)`; a checksum mismatch is an integrity failure.
- Offset/limit APIs use allow-listed filters and stable ID tie-breaking.

## Task slices

### CPS-301 — typed persistence foundation

- Add typed ORM models for region, project, flavor, image, instance, network, subnet, port, and volume.
- Add instance-port and instance-volume relationship tables with provider IDs and lifecycle attributes.
- Add common identity, lifecycle, sync, provider-attributes, timestamp, and version columns.
- Add named uniqueness, foreign keys, check constraints, and indexes.
- Add Alembic migration and metadata/schema tests.

### CPS-302/303 — ingestion and reconciliation

- Define canonical inventory batch/completion contracts and fixtures first.
- Add inventory sync/batch persistence and a transactionally idempotent inbox handler.
- Validate sequence, count, checksum, `is_last`, resource type, and duplicate replay.
- Track required collection outcomes and finalize only complete successful syncs.

### CPS-304/305 — API and operations

- Add shared resource projections and nine typed list/get routes.
- Add full-sync and targeted-refresh operation creation with idempotency.
- Publish reference-only commands through the existing outbox.
- Apply tombstones only for explicit provider NotFound results.

### OPS-301..305 — provider adapter

- Add bounded collection coordinator and per-service collectors.
- Map SDK resources into contract-safe typed items; never serialize SDK objects.
- Publish deterministic confirmed batches and terminal collection outcomes.
- Implement targeted refresh with safe NotFound/timing/auth/service distinction.

## Review gates per slice

1. CodeGraph blast-radius query before edits.
2. Failing test observed for the acceptance rule.
3. Focused tests and affected integration tests pass.
4. Diff, secret scan, Ruff/mypy, and migration/schema checks pass.
5. Sprint backlog status/evidence updated only for criteria actually demonstrated.
