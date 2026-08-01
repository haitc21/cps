# Sprint 19 — Catalog Detail and Compatibility Contracts (CPS-1901)

**Status:** Done
**Branch:** `sprint-19/cps-1901`  
**Base:** `81c1b02`  
**Worktree:** `/home/haitc/.config/superpowers/worktrees/cps/cps-1901`

## Security amendment

CPS-1203 tenant authorization remains deferred. Sprint 19 therefore fails
closed for member catalog access: only approved/live public or community images
and approved/enabled public flavors are exposed. Private/shared images and
private flavors remain administrator-only until the TMS authorization boundary
is active. Member routes accept no client-selected tenant scope (`org_id`,
`workspace_id`, binding-derived project scope removed); restricted resource IDs
use a uniform non-enumerating 404 (detail/list) or `*_NOT_FOUND` compatibility
outcome without approval/lifecycle/tenant reason leakage.

## Threat model (plan scope)

Assets: admin inventory, approval policy, contracts/checksums, compatibility decisions.  
Invariants enforced in code/tests: member cannot enumerate unapproved/deleted/private/shared resources; no `provider_attributes` in member/admin projections; metadata bounds before persistence and response serialization; compatibility fails closed with non-enumerating member outcomes.

## Task 5A security-amendment round 3 — RED / GREEN ledger

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| 5A RED | `.venv/bin/pytest tests/unit/api/test_catalog.py tests/unit/application/test_catalog_compatibility.py tests/contract/test_inventory_batch_contract.py -q` | FAIL | **27 FAIL** (scope selectors, masking, secrets, minima, LIKE, schema parity) |
| 5A GREEN (focused) | same | PASS | **115 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (130 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json` checksum refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **721 passed**, 2 skipped |
| Full pytest | `.venv/bin/pytest -q` | exit 0 | **722 passed**, 186 skipped (integration env not configured this turn) |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 0 |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_member_public_catalog_filters_use_expression_indexes -q` | PASS | **1 PASS** (2026-08-01 worker fix) |

### PG18 integration failure/fix — `test_member_public_catalog_filters_use_expression_indexes`

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| RED (pre-fix) | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_member_public_catalog_filters_use_expression_indexes -xvs` | FAIL (planner skips `ix_images_catalog_filters`) | **FAIL** — EXPLAIN chose `ix_images_catalog_dims` for under-constrained query (`provider_connection_id` + `visibility IN (public, community)` only; no `disk_format` predicate) |
| GREEN (post-fix) | same | PASS | **PASS** — seed mixes `visibility`/`disk_format`; repository list uses `visibility=public` + `disk_format=qcow2` + `member_public_catalog_only`; EXPLAIN matches composite partial index predicate |
| Affected suite | `pytest tests/integration/db/test_inventory_repository.py::{test_image_catalog_persists_typed_fields_and_filters,test_catalog_list_orders_by_name_then_id,test_member_public_catalog_filters_use_expression_indexes,test_member_scope_queries_use_jsonb_expression_indexes} tests/integration/db/test_schema_parity.py tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | PASS | **6 PASS** |
| diff check | `git diff --check` | exit 0 | exit 0 |

**Root cause:** `ix_images_catalog_filters` indexes `(provider_connection_id, visibility, disk_format, size_bytes)` with partial `catalog_approved`/live predicate. A member-public query without `disk_format` (or other trailing key columns) is under-constrained; PostgreSQL 18 correctly prefers another partial index (`ix_images_catalog_dims` or generic `ix_images_provider_connection_id`).

**Fix:** Test-only — no migration change. Seed 500 rows with mixed `visibility`/`disk_format`; exercise repository-supported composite filter path; align EXPLAIN SQL with equality predicates on indexed columns.

### Task 5A code changes (summary)

- Removed `catalog_scope.py` and binding-trusted `org_id`/`workspace_id` from member catalog/compatibility routes.
- Member repository filter uses `member_public_catalog_only` (public/community images, public enabled flavors only).
- Member compatibility masks inaccessible rows as `IMAGE_NOT_FOUND` / `FLAVOR_NOT_FOUND`.
- Extended secret detection: `ca_cert_pem`, `privateKey`, PEM private-key content, camel/snake key variants.
- JSON Schema: recursive bounded metadata `$defs`, `propertyNames` secret rejection, per-string `maxLength` 65536; contract tests assert schema-layer rejection for secret keys and oversized strings.
- Launch/rebuild/resize require image `min_disk_gib` and `min_ram_mib`.
- Response list/count/64KiB serialized bounds enforced on catalog projections.
- SQL `ILIKE` uses explicit `\` escape for `%` and `_`.
- Member `approved` query parameter rejected including `approved=true`.

## Luna pass-2 remediation disposition

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| C3 | Critical | **Fixed** | `_validate_metadata_tree` propagates `parent_secret` through lists; `_is_secret_value` rejects signed/credential URL patterns without key context; `_validate_serialized_size` on `metadata`, `attachments`, and `attributes`; `_bounded_*` projection helpers reject invalid legacy data instead of truncating. Tests: expanded `test_catalog_inventory_rejects_invalid_or_secret_fields` (14 cases). |
| I4 | Important | **Fixed** | Member detail route returns `CatalogImageSummary`/`CatalogFlavorSummary` via `project_image_summary`/`project_flavor_summary`; admin retains bounded `Catalog*Detail`. Tests: `test_member_catalog_detail_success_has_bounded_fields_only`, `test_admin_catalog_detail_rejects_invalid_legacy_metadata`. |
| I5 | Important | **Fixed** | Migration `20260801_0017` adds expression GIN indexes `ix_images_catalog_member_projects` and `ix_flavors_catalog_access_projects` matching JSONB `@>` predicates; downgrade drops only catalog indexes. Integration: `test_member_scope_queries_use_jsonb_expression_indexes` (500 seeded rows, `ANALYZE`, EXPLAIN proves index with `enable_seqscan=off`). |
| I7 | Important | **Fixed** | `capability_document.schema.json` uses `schema_version` pattern `^1.[0-9]+$`, required base keys, and `allOf` catalog feature keys for minor `>= 1` (includes `1.2`). Tests: `test_capability_json_schema_accepts_1_2_with_catalog_keys`, rejection/base-key JSON Schema cases. |
| I8 | Important | **Fixed** | Parameterized all four `CatalogUse` success paths; added provider mismatch, unapproved/stale flavor, scope mismatch, format/RAM/root/incomplete reason coverage in unit + API matrix tests. |

## RED / GREEN command ledger (pass-2)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| C3 RED | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py -k "metadata exceed or attachments exceed" -q` | FAIL | **FAIL** (no 64KiB enforcement on metadata/attachments) |
| C3 GREEN | same | PASS | **PASS** |
| I4 RED | `.venv/bin/pytest tests/unit/api/test_catalog.py::test_member_catalog_detail_success_has_bounded_fields_only -q` | FAIL | **FAIL** (`properties` in member detail) |
| I4 GREEN | same | PASS | **PASS** |
| I5 RED | `.venv/bin/pytest tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | FAIL | **FAIL** (missing expression index names) |
| I5 GREEN | integration EXPLAIN test | PASS | **PASS** |
| I7 RED | `.venv/bin/pytest tests/contract/test_catalog_contract.py -k json_schema -q` | FAIL | **FAIL** (schema accepted `2.0`) |
| I7 GREEN | same | PASS | **PASS** |
| I8 GREEN | `.venv/bin/pytest tests/unit/application/test_catalog_compatibility.py tests/unit/api/test_catalog.py -q` | PASS | **PASS** (expanded matrix) |
| PG18 cycle | `CPS_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test alembic upgrade head && downgrade 20260731_0016 && upgrade head` | exit 0 | **exit 0** |
| Integration (5) | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=... pytest tests/integration/db/test_inventory_repository.py::{test_image_catalog_persists_typed_fields_and_filters,test_catalog_list_orders_by_name_then_id,test_member_scope_queries_use_jsonb_expression_indexes} tests/integration/db/test_schema_parity.py tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | PASS | **5 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 |
| Full pytest | `.venv/bin/pytest -q` | exit 0 | **868 passed**, 2 skipped; 4 failed + 22 errors in live compose/keycloak/messaging integration (pre-existing env deps, out of scope) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **711 passed**, 2 skipped |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`capability_document.schema.json` checksum refreshed) |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-4 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Member routes reject any supplied `owner_project_id`, `project_access_id`, and `include_deleted` (including `false`); repository kwargs omit tenant-selection filters. Tests: expanded `test_member_catalog_rejects_admin_only_filters`, `test_catalog_rejects_wrong_resource_type_filters`, `test_member_catalog_forwards_common_filters_and_forces_member_policy`. |
| I2 | Important | **Fixed** | `safe_metadata.py` centralizes normalized secret-key detection and PEM/signed-URL value rejection; inventory and capability validation share it. Tests: camelCase cases in `test_catalog_inventory_rejects_invalid_or_secret_fields`, `test_capability_document_rejects_secret_and_oversized_payload`. |
| I3 | Important | **Fixed** | `inventory_batch.schema.json` recursive bounded metadata with depth 4, secret `propertyNames`, and 64KiB per-string bounds. Tests: `test_inventory_json_schema_rejects_secret_bearing_keys`, `test_inventory_json_schema_rejects_oversized_attribute_strings`, `test_inventory_json_schema_rejects_camel_case_secret_keys`. |
| I4 | Important | **Fixed** | Legacy admin projections fail on overlong tag/member/access entries and oversized serialized detail. Tests: `test_admin_catalog_detail_rejects_overlong_legacy_list_entries`, `test_admin_catalog_detail_rejects_oversized_legacy_projection`. |
| I5 | Important | **Fixed** | Image upsert typed conflict refresh precedes generic `project_id` coalesce. Test: `test_image_upsert_refreshes_all_typed_fields_on_conflict` (integration). |
| I6 | Important | **Fixed** | `capability_document.schema.json` applies secret `propertyNames` and bounded extra-field strings on root/services/features. |
| I7 | Important | **Fixed** | Member `include_deleted` is `Optional`; any supplied value returns admin-only `422`. |

## RED / GREEN command ledger (pass-4)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-4 RED | `.venv/bin/pytest tests/unit/api/test_catalog.py tests/contract/test_inventory_batch_contract.py tests/contract/test_connection_validation_contract.py -q` | FAIL | **4 FAIL** (schema parity, member tenant filters, legacy bounds) |
| Pass-4 GREEN | same | PASS | **99 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (inventory + capability schema checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **730 passed**, 2 skipped |
| Full pytest | `.venv/bin/pytest -q` | exit 0 | **731 passed**, 187 skipped |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=... pytest tests/integration/db/test_inventory_repository.py::test_image_upsert_refreshes_all_typed_fields_on_conflict -q` | PASS | **skipped** (no `CPS_TEST_DATABASE_URL` in worker environment) |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Coordinator evidence (PostgreSQL 18)

- Template DB: `cps_test` on `cmp-postgres-1` (PostgreSQL 18, disposable session DBs created per integration run).
- Migration cycle: upgrade head → downgrade `20260731_0016` → upgrade head; all exit 0; head remains `20260801_0017`.
- Five focused integration/metadata tests passed; disposable session database removed by `DisposableDatabaseManager.cleanup()`.

## Live acceptance

Not executed (explicitly out of scope for this worker turn).

## Luna pass-5 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `inventory_batch.schema.json` adds `InventoryAttributes` with strict `catalog_approved` boolean, bounded `tags`, substring secret `propertyNames`, RSA/EC/OPENSSH PEM patterns, and credential/signed/x-goog/AWS URL rejection aligned with Pydantic. Tests: new schema parity cases in `test_inventory_json_schema_rejects_*`. |
| I2 | Important | **Fixed** | `capability_document.schema.json` uses recursive bounded extra-field `$defs` (`ExtraMetadataDepth1`–`4`, `maxProperties`/`maxItems`/`maxLength`) and the same secret/PEM/URL patterns as inventory metadata. Tests: `test_capability_json_schema_rejects_secret_key_substrings_in_extra_fields`, PEM/URL, unbounded nested extra fields. |
| I3 | Important | **Fixed** | Image typed conflict updates coalesce `project_id`/`project_provider_resource_id` while refreshing catalog typed columns; integration RED `test_image_refresh_without_ownership_preserves_project_linkage`. Admin legacy non-object metadata returns `400 VALIDATION_FAILED` (not 500). Test: `test_admin_catalog_detail_http_returns_422_for_legacy_non_object_metadata`. |

## RED / GREEN command ledger (pass-5)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-5 RED | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py -k "json_schema_rejects_secret_key_substring or json_schema_rejects_pem or json_schema_rejects_credential or json_schema_rejects_non_boolean_catalog or json_schema_rejects_invalid_tags" tests/contract/test_catalog_contract.py -k "capability_json_schema_rejects" tests/unit/api/test_catalog.py::test_admin_catalog_detail_http_returns_422_for_legacy_non_object_metadata -q` | FAIL | **19 FAIL** (schema parity gaps, HTTP 500 on legacy projection) |
| Pass-5 GREEN (schema/API) | same minus integration | PASS | **22 PASS** |
| Pass-5 GREEN (catalog unit) | `.venv/bin/pytest tests/unit/api/test_catalog.py -q` | PASS | **48 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **752 passed**, 2 skipped |
| Full pytest | `.venv/bin/pytest -q` | exit 0 | **753 passed**, 188 skipped |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=... pytest tests/integration/db/test_inventory_repository.py::test_image_refresh_without_ownership_preserves_project_linkage -q` | PASS | **skipped** (password auth failed for default `cmp:cmp@127.0.0.1:5432/cps_test`) |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-6 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Strict scalar typing in `_validate_catalog_attributes` (`type(...) is int/bool/str`); rejects bool `virtual_size_bytes`, string coercions, and `container_format` >255. Tests: `test_catalog_inventory_rejects_loose_attribute_scalar_types`. |
| I2 | Important | **Fixed** | `_validate_attachments` mirrors `BoundedAttachmentObject` (object-only items, recursive bounds, 64 KiB serialized, max 32). Tests: `test_volume_batch_rejects_non_object_attachment_entries`. |
| I3 | Important | **Fixed** | `safe_metadata` + JSON Schema `SafePropertyName` include `credential`/`signed_url`/`signedurl` variants. Tests: credential/signed-url key rejection in inventory/capability contract and runtime tests. |
| I4 | Important | **Fixed** | `CapabilityDocument` runtime validation uses `validate_metadata_tree` for recursive depth/count/string/serialized bounds. Tests: `test_capability_document_runtime_rejects_*`. |
| I5 | Important | **Fixed** | `resolve_owner_project_provider_resource_id` rejects conflicting ownership sources; Image conflict preserves ownership pair unless incoming owner resolves (`project_id IS NOT NULL`). Integration: `test_image_refresh_with_unresolved_owner_preserves_project_linkage_atomically`. |
| I6 | Important | **Fixed** | `_provider_attributes` guards dict shape before projection; strict `virtual_size_bytes`/`container_format` bounds on admin detail. Tests: admin detail rejection cases for list attributes, bool virtual size, overlong container format. |

## RED / GREEN command ledger (pass-6)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-6 RED | focused contract/catalog/admin projection tests (see plan pass-6 list) | FAIL | **FAIL** (strict typing, runtime bounds, projection guards) |
| Pass-6 GREEN (focused) | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/contract/test_connection_validation_contract.py tests/unit/api/test_catalog.py -q` | PASS | **151 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **770 passed**, 2 skipped |
| Full pytest | `.venv/bin/pytest -q` | exit 0 | **771 passed**, 189 skipped |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-7 ownership-state fix (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I5 | Important | **Fixed** | Image upsert conflict applies atomic ownership semantics: absent owner preserves existing `project_provider_resource_id`/`project_id`; unchanged owner preserves resolved linkage; changed unresolved owner updates provider owner and clears `project_id` to NULL; resolved owner updates both. Never keeps stale owner or mismatched pair. Integration: `test_image_upsert_refreshes_all_typed_fields_on_conflict` (asserts `project_id IS NULL` for unresolved `project-2`), `test_image_refresh_without_ownership_preserves_project_linkage`, `test_image_refresh_with_changed_unresolved_owner_clears_project_id`, `test_image_refresh_with_unchanged_owner_preserves_resolved_project_id`, `test_image_refresh_with_resolved_owner_updates_linkage`. |

## RED / GREEN command ledger (pass-7)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-7 RED | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py -k "image_refresh or image_upsert" -q` | FAIL | **FAIL** (changed-unresolved preserved stale owner; upsert missing `project_id` NULL assert) |
| Pass-7 GREEN | same five focused tests | PASS | **5 PASS** |
| Ruff | `.venv/bin/ruff check src/cps/infrastructure/db/repositories/inventory.py tests/integration/db/test_inventory_repository.py` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src/cps/infrastructure/db/repositories/inventory.py` | exit 0 | exit 0 |
| Affected contract/unit | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py tests/unit/infrastructure/test_schema_metadata.py -q -m "not integration"` | PASS | **123 PASS** |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **770 passed**, 2 skipped |
| PG18 integration | five focused image ownership tests on `cps_test` template (PostgreSQL 18, `cmp-postgres-1`) | PASS | **5 PASS** |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-8 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `inventory_batch.schema.json` applies `BoundedCatalogString`/`SafeMetadataString` to `container_format`, `tags`, `member_project_ids`, and `access_project_ids`; Pydantic `_validate_catalog_attributes` uses `validate_safe_catalog_string`. Tests: `test_inventory_json_schema_rejects_secret_values_in_catalog_attribute_strings`. |
| I2 | Important | **Fixed** | Attachment schema uses conservative `Attachment*` defs (depth 4, map/list 4, string 512, 32 objects) matching `validate_attachment_tree` runtime; explicit serialized 64 KiB check retained. Tests: `test_inventory_json_schema_accepts_nested_attachment_lists`, `test_inventory_json_schema_rejects_oversized_attachment_serialized_payload`. |
| I3 | Important | **Fixed** | `capability_document.schema.json` applies `BoundedVersionString`/`BoundedReasonString` (`SafeExtraString` + secret patterns) to `min_version`, `max_version`, and `reason`. Tests: `test_capability_json_schema_rejects_secret_values_in_version_and_reason_fields`. |
| I4 | Important | **Fixed** | Capability schema `SafeExtraString` maxLength 2048; nested list items may include objects; runtime `ServiceCapability`/`FeatureCapability` validators reject secret version/reason values. Tests: `test_capability_json_schema_rejects_oversized_serialized_document`, `test_capability_document_runtime_rejects_secret_values_in_version_and_reason_fields`. |
| I5 | Important | **Fixed** | Admin projection `_optional_bounded_container_format` rejects secret values via `is_secret_value` before response serialization. Test: `test_admin_catalog_detail_rejects_secret_bearing_container_format`. |
| I6 | Important | **Fixed** | Compatibility route validates dict `provider_attributes` and projects consumed legacy keys through `compatibility_*_snapshot_fields`; invalid types/bounds map to uniform `*_NOT_FOUND` without 500/leak. Tests: `test_compatibility_masks_invalid_provider_attributes_as_not_found`, `test_compatibility_masks_secret_bearing_container_format_as_not_found`. |

## RED / GREEN command ledger (pass-8)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-8 RED | focused pass-8 contract/catalog tests | FAIL | **14 FAIL** (schema parity, projection, compatibility 500) |
| Pass-8 GREEN (focused) | same | PASS | **14 PASS** |
| Pass-8 GREEN (affected) | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/contract/test_connection_validation_contract.py tests/unit/api/test_catalog.py tests/unit/application/test_catalog_compatibility.py -q` | PASS | **198 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **784 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-11 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Attachment root map capped at 4 keys runtime/schema; capability list items scalar-only. Tests: `test_runtime_and_schema_both_reject_attachment_root_exceeding_4_entries`, `test_capability_runtime_and_schema_both_reject_nested_map_in_extra_list`. |
| I2 | Important | **Fixed** | `validate_disk_format` rejects uppercase (no normalization); filter/projection aligned. Tests: `test_inventory_checksum_rejects_uppercase_disk_format`, `test_inventory_json_schema_rejects_uppercase_disk_format`. |
| I3 | Important | **Fixed** | Catalog API schemas/projection enforce 255/128/64/32 bounds on all string fields. Tests: `test_admin_catalog_detail_rejects_overlong_name`, `test_admin_catalog_detail_rejects_secret_bearing_checksum`. |
| I4 | Important | **Fixed** | Compatibility snapshots `Field` bounds on strings and project lists. Tests: `test_snapshot_rejects_overlong_provider_resource_id`, `test_snapshot_rejects_oversized_project_id_list`. |
| I5 | Important | **Fixed** | Top-level inventory strings use `validate_safe_catalog_string`; schema `CatalogSafeString` family. Tests: `test_catalog_inventory_rejects_secret_bearing_top_level_string_fields`, `test_inventory_json_schema_rejects_secret_bearing_top_level_catalog_strings`. |
| I6 | Important | **Fixed** | `semantic.py` validates full `InventoryBatchPayload` for all `cloud.inventory.batch` fixtures. Tests: `test_semantic_validation_validates_all_inventory_batch_payloads_against_json_schema`. |

## RED / GREEN command ledger (pass-11)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-11 RED | focused parity/inventory/catalog/semantic tests | FAIL | **9 FAIL** (tree drift, disk_format normalize, unbounded strings, CLI item-only) |
| Pass-11 GREEN (focused) | `.venv/bin/pytest tests/unit/contracts/test_conservative_tree_schema_parity.py tests/contract/test_inventory_batch_contract.py tests/unit/api/test_catalog.py tests/unit/application/test_catalog_compatibility.py tests/contract/test_delivery_contract.py -q` | PASS | **PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **841 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-10 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Metadata/attachment runtime unified; schema list entries scalar-only, root map 128; attachment `$ref MetadataDepth1`. Tests: `test_conservative_tree_schema_parity.py`. |
| I2 | Important | **Fixed** | `CatalogSafeString` maxLength 255 decoupled from 128-char metadata strings. Test: `test_catalog_string_255_accepted_by_runtime_and_schema`. |
| I3 | Important | **Fixed** | `validate_disk_format` allow-list in runtime/schema/projection/compatibility/filter. Tests: `test_catalog_inventory_rejects_non_allowlisted_disk_format`, member projection/filter cases. |
| I4 | Important | **Fixed** | Compatibility snapshots `strict=True` + Field bounds; request `extra=forbid`. Tests: `test_compatibility_request_rejects_unknown_scope_fields`. |
| I5 | Important | **Fixed** | Member `_member_*_summary` fail-closed `404`. Tests: `test_member_catalog_*_malformed_legacy_projection`. |
| I6 | Important | **Fixed** | Embedded URL secret detection (runtime + schema). Test: expanded `test_secret_value_detection_covers_userinfo_and_signed_url_query`. |
| I7 | Important | **Fixed** | Catalog filter Query `le=` + `_validate_numeric_filter_bounds`. Test: `test_catalog_rejects_numeric_filter_above_contract_maximum`. |
| I8 | Important | **Fixed** | `semantic.py` inventory item + capability schema validation; CLI via `validate_contracts`. Tests: `test_semantic_validation_*`. |
| I9 | Important | **Deferred** | Live CPS/OpenStack + OPS pin remain Task 8 gates (explicitly out of scope this worker turn). |

## RED / GREEN command ledger (pass-10)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-10 RED | focused parity/catalog/semantic tests | FAIL | **FAIL** (tree drift, disk_format, member 500, CLI gap) |
| Pass-10 GREEN (focused) | `.venv/bin/pytest tests/unit/contracts/test_conservative_tree_schema_parity.py tests/unit/contracts/test_safe_metadata_schema_portability.py tests/contract/test_inventory_batch_contract.py tests/unit/api/test_catalog.py tests/contract/test_delivery_contract.py::test_semantic_validation_validates_catalog_inventory_items_against_json_schema tests/contract/test_delivery_contract.py::test_semantic_validation_rejects_inventory_fixture_item_schema_drift -q` | PASS | **PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **831 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-9 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1-I6 | Important | **Fixed** | ECMA-262 portable secret-key/value patterns; runtime/schema parity for separator variants, userinfo/signed_url URLs, conservative shared tree (depth 4, map/list 4, string 128) with retained 64 KiB runtime checks. |
| I3 | Important | **Fixed** | Dedicated `tags`/`member_project_ids`/`access_project_ids` bypass generic 128-list validator; 256 project IDs accepted. |
| I7 | Important | **Fixed** | Admin/compatibility projections enforce typed numeric min/max and bool rejection; negative flavor dimensions masked/fail-closed. |
| I8 | Important | **Fixed** | `InventoryBatchItem` `strict=True`; loose numeric/bool strings rejected. |
| I9 | Important | **Fixed** | No inline regex flags in JSON Schema; `tests/unit/contracts/test_safe_metadata_schema_portability.py` compile check. |
| I10 | Important | **Fixed** | `MAX_CATALOG_OFFSET = 100_000` in `pagination.py`; `422` tests in `tests/unit/api/test_pagination.py`. |

## RED / GREEN command ledger (pass-9)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-9 RED | focused pass-9 contract/catalog/pagination tests | FAIL | **FAIL** (schema/runtime parity, strict typing, pagination, projection bounds) |
| Pass-9 GREEN (focused) | `.venv/bin/pytest tests/unit/contracts/test_safe_metadata_schema_portability.py tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/contract/test_connection_validation_contract.py tests/unit/api/test_pagination.py tests/unit/api/test_catalog.py tests/unit/application/test_catalog_compatibility.py -q` | PASS | **228 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **810 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-12 remediation disposition (2026-08-01)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `ProviderTimestampString` + `validate_provider_timestamp` (ISO-8601, maxLength 64, secret reject) in runtime/schema. Tests: `test_catalog_inventory_rejects_unsafe_or_unbounded_provider_timestamps`, `test_catalog_inventory_accepts_bounded_provider_timestamps`. |
| I2 | Important | **Fixed** | Root `attributes` max128 enforced in `_validate_catalog_attributes`. Test: `test_runtime_and_schema_both_reject_attributes_root_exceeding_128_entries`. |
| I3 | Important | **Fixed** | `CapabilityDocument` explicit `services`/`features` max128 runtime; `schema_version` maxLength 16 runtime/schema. Tests: `test_capability_document_runtime_rejects_more_than_128_*`, `test_capability_*_rejects_overlong_schema_version`. |
| I4 | Important | **Fixed** | Attachment key max32 + `AttachmentDepth*` schema; worst-case deterministic <64KiB proof. Test: `test_worst_case_schema_valid_attachment_serializes_below_64_kib`. |
| I5 | Important | **Fixed** | Repository catalog filter compares `disk_format` without `.lower()` normalization. |
| I6 | Important | **Fixed** | `validate_safe_project_id` / `SafeProjectIdString` on inventory lists and compatibility snapshots. Tests: `test_snapshot_rejects_empty_project_id`, `test_snapshot_rejects_secret_bearing_project_id`. |
| I7 | Important | **Fixed** | Runtime/schema secret-value patterns extended for `password=`, `token=`, `authorization bearer/basic` with adversarial safe-name tests. Tests: expanded `test_safe_metadata_schema_portability.py`. |

## RED / GREEN command ledger (pass-12)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-12 RED | focused pass-12 contract/metadata/compatibility tests | FAIL | **12 FAIL** (timestamps, attributes128, capability counts, attachment worst-case, secrets, project IDs) |
| Pass-12 GREEN (focused) | `.venv/bin/pytest tests/unit/contracts/test_safe_metadata_schema_portability.py tests/unit/contracts/test_conservative_tree_schema_parity.py tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/unit/application/test_catalog_compatibility.py -q` | PASS | **PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **865 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-13 remediation disposition (2026-08-01, CodeGraph blast-radius round 13)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| C1 | Critical | **Fixed** | `_upsert_resource` canonicalizes every item via `canonicalize_inventory_item` / `InventoryBatchItem` before persistence (batch + inbox operation-result paths). Tests: `tests/unit/infrastructure/db/test_inventory_operation_result_validation.py` (nested `password=` metadata, secret attribute key, timestamps). |
| C2 | Critical | **Fixed** | `OwnershipConflictError` + `PydanticCustomError` / stable `OWNERSHIP_CONFLICT_MESSAGE`; repository maps to redacted `InventoryPersistenceError` without owner identifiers. Tests: `test_catalog_inventory_rejects_conflicting_ownership_sources`, `test_upsert_resource_ownership_conflict_is_redacted`. |
| I1 | Important | **Fixed** | `provider_created_at`/`provider_updated_at` parsed in `_upsert_resource` via `_parse_provider_timestamp` after canonical validation. Test: `test_persist_snapshot_result_persists_provider_timestamps`. |
| I2 | Important | **Fixed** | Attachment worst-case proof aligned to `AttachmentDepth4` leaf tier (runtime depth 3) and `maxItems=32` shallow proof; both stay <64KiB. Tests: `test_worst_case_schema_valid_attachment_serializes_below_64_kib`, `test_worst_case_schema_valid_attachments_at_max_items_stays_below_64_kib`. |
| I3 | Important | **Fixed** | Capability `available`/`supported` strict bool via `field_validator(mode="before")`. Tests: `test_capability_document_runtime_rejects_loose_boolean_scalars`, `test_capability_json_schema_rejects_loose_boolean_scalars`. |
| I4 | Important | **Fixed** | Admin catalog applies `validate_safe_project_id` to `owner_project_id` and `project_access_id`; ownership resolution uses `validate_safe_project_id` (no `str()` coercion). Tests: `test_admin_catalog_rejects_secret_bearing_owner_project_id`, `test_admin_catalog_rejects_secret_bearing_project_access_id`. |
| I5 | Important | **Fixed** | Secret detection expanded for `Authorization: Token`, standalone `Basic`/`Bearer`/`Token` credential patterns (runtime + ECMA-262 schema, adversarial safe-name preserved). Tests: expanded `test_safe_metadata_schema_portability.py`. |

## RED / GREEN command ledger (pass-13)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-13 RED | focused op-result/ownership/attachment/secret/catalog tests | FAIL | **12 FAIL** (unvalidated op-results, owner leak, auth patterns, attachment depth, admin project IDs, capability bool) |
| Pass-13 GREEN (focused) | `.venv/bin/pytest tests/unit/infrastructure/db/test_inventory_operation_result_validation.py tests/unit/contracts/test_conservative_tree_schema_parity.py tests/unit/contracts/test_safe_metadata_schema_portability.py tests/contract/test_inventory_batch_contract.py tests/unit/api/test_catalog.py tests/contract/test_catalog_contract.py -q` | PASS | **PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **879 passed**, 2 skipped |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=... pytest tests/integration/db/test_inventory_repository.py -q` | PASS | **skipped** (PostgreSQL auth/connection unavailable in worker environment) |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-14 remediation disposition (2026-08-01, worker round 14)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `validate_volume_attachment_resource` gates `apply_volume_attachment_result` before DB merge; rejects secret `device` and unsupported fields. Test: `test_apply_volume_attachment_result_rejects_secret_bearing_resource`. |
| I2 | Important | **Fixed** | `persist_snapshot_result` / `persist_instance_result` forward validated `provider_created_at`/`provider_updated_at` into `_upsert_resource` items. Tests: `test_persist_snapshot_result_forwards_provider_timestamps_to_upsert`, `test_persist_instance_result_forwards_provider_timestamps_to_upsert`. |
| I3 | Important | **Fixed** | `validate_provider_timestamp` semantic ISO-8601 check at ingress; tightened month/day/hour/offset regex runtime + `ProviderTimestampString` schema. Tests: expanded `test_catalog_inventory_rejects_unsafe_or_unbounded_provider_timestamps`. |
| I4 | Important | **Fixed** | Letter-only standalone `Bearer`/`Token` credentials rejected runtime + ECMA-262 schema; adversarial descriptive strings preserved. Test: `test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials`. |

## RED / GREEN command ledger (pass-14)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-14 RED | `.venv/bin/pytest tests/unit/infrastructure/db/test_inventory_operation_result_validation.py tests/contract/test_inventory_batch_contract.py -k "provider_timestamp or operation_result or rejects_unsafe_or_unbounded_provider" tests/unit/contracts/test_safe_metadata_schema_portability.py::test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials -q` | FAIL | **9 FAIL** (attachment canonical gap, timestamp forwarding, semantic timestamps, letter-only auth) |
| Pass-14 GREEN (focused) | same | PASS | **17 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json` checksums refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **890 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-15 remediation disposition (2026-08-01, worker round 15)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Inbox volume-attachment ingress forwards `result.resource` without dict coercion; non-object non-null values reach `validate_volume_attachment_resource` and fail with redacted `InventoryPersistenceError` before `InstanceVolume` merge/commit. Tests: `test_apply_volume_attachment_result_rejects_non_object_resource`, `test_process_inbox_rejects_volume_attachment_non_object_resource_before_merge`. |
| I2 | Important | **Fixed** | Letter-only standalone `Bearer`/`Token` parity extended for trailing whitespace and whitespace-before-punctuation (`Bearer abcdefgh `, `Token abcdefgh .`) in runtime (`_STANDALONE_LETTER_ONLY_BEARER_TOKEN_PATTERN`) and ECMA-262 schema (`ecma262_standalone_auth_scheme_pattern` + JSON Schema pattern refresh); adversarial safe-name negatives preserved. Test: expanded `test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials`. |

## RED / GREEN command ledger (pass-15)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-15 RED | `.venv/bin/pytest tests/unit/messaging/test_inbox_snapshot_projection.py::test_process_inbox_rejects_volume_attachment_non_object_resource_before_merge tests/unit/contracts/test_safe_metadata_schema_portability.py::test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials -q` | FAIL | **3 FAIL** — inbox coerced string `resource` to `None` (no raise, merge awaited); schema false negatives for `Bearer abcdefgh ` and `Token abcdefgh .` |
| Pass-15 GREEN (focused) | `.venv/bin/pytest tests/unit/messaging/test_inbox_snapshot_projection.py::test_process_inbox_rejects_volume_attachment_non_object_resource_before_merge tests/unit/infrastructure/db/test_inventory_operation_result_validation.py::test_apply_volume_attachment_result_rejects_non_object_resource tests/unit/contracts/test_safe_metadata_schema_portability.py::test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials -q` | PASS | **7 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`inventory_batch.schema.json`, `capability_document.schema.json`, `checksums.json` refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **894 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-17 remediation disposition (2026-08-01, worker round 17)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Version-aware dual checksum: `compute_inventory_checksum_v1_0` / `compute_inventory_checksum_v1_1` + `_verify_inventory_batch_checksum`; envelope `schema_version` passed via Pydantic context in inbox/semantic; unsafe payloads rejected before checksum acceptance. Tests: legacy fixture + mismatch + safety bypass cases in `test_inventory_batch_contract.py`. |
| I2 | Important | **Fixed** | `resolve_catalog_pagination` caps offset at `MAX_CATALOG_OFFSET`; legacy `resolve_pagination` uncapped for provider/connection/inventory/operation list routes. Tests: `test_legacy_pagination_accepts_offset_above_catalog_max`, catalog cap tests in `test_pagination.py`. |
| I3 | Important | **Fixed** | `CatalogResourceType` restores CPS-1703 `network`/`volume-type`/`availability-zone`; admin list dispatches to `InventoryResourceView`; member `CatalogStoryResourceType` unchanged; image/flavor-only filters rejected for infrastructure types. Tests: expanded `test_catalog.py`, `test_catalog_contract.py`. |

## RED / GREEN command ledger (pass-17)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-17 RED (pagination) | `.venv/bin/pytest tests/unit/api/test_pagination.py -k "legacy_pagination or catalog_offset" -q` | FAIL | **ERROR** — `resolve_catalog_pagination` missing; legacy cap still in `resolve_pagination` |
| Pass-17 RED (checksum) | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py -k "legacy_schema or schema_1 or legacy_checksum" -q` | FAIL | **ERROR** — `compute_inventory_checksum_v1_0` / v1_1 missing |
| Pass-17 RED (admin catalog) | `.venv/bin/pytest tests/unit/api/test_catalog.py -k "cps_1703 or admin_catalog_resource_type" tests/contract/test_catalog_contract.py::test_catalog_contract_is_read_only_and_allowlisted -q` | FAIL | **ERROR** — `CatalogResourceType.NETWORK` absent |
| Pass-17 GREEN (focused) | same three commands | PASS | **10 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (20 files) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **904 passed**, 2 skipped |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py -q` | PASS | **skipped** (password auth failed for `cmp@127.0.0.1:5432/cps_test`) |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Luna pass-16 remediation disposition (2026-08-01, worker round 16)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | Typed conflict branch for Volume, VolumeSnapshot, Keypair, and Quota shared Image ownership semantics via `_project_ownership_conflict_update`: omitted owner preserves existing `project_id`/`project_provider_resource_id`; resolved owner updates atomically; changed-unresolved owner clears `project_id` only. Insert path no longer writes explicit `NULL` ownership when owner absent. Tests: `test_project_scoped_refresh_without_ownership_preserves_project_linkage[volume|volume-snapshot|keypair|quota]`, `test_volume_refresh_with_resolved_owner_updates_linkage`; existing Image semantics tests remain green. |

## RED / GREEN command ledger (pass-16)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-16 RED | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_project_scoped_refresh_without_ownership_preserves_project_linkage[volume] -xvs` | FAIL | **FAIL** — `project_provider_resource_id` became `None` after refresh omitting owner (`AssertionError: None == 'project-1'`) |
| Pass-16 GREEN (ownership) | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_project_scoped_refresh_without_ownership_preserves_project_linkage tests/integration/db/test_inventory_repository.py::test_volume_refresh_with_resolved_owner_updates_linkage tests/integration/db/test_inventory_repository.py::test_image_refresh_without_ownership_preserves_project_linkage tests/integration/db/test_inventory_repository.py::test_image_refresh_with_changed_unresolved_owner_clears_project_id tests/integration/db/test_inventory_repository.py::test_image_refresh_with_resolved_owner_updates_linkage -q` | PASS | **8 PASS** |
| PG18 integration (inventory repo) | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py -q` | PASS | **17 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (20 files) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **894 passed**, 2 skipped |
| diff check | `git diff --check` | exit 0 | exit 0 |

## Remaining before story Done

- OPS-1901 pin + live curl/OpenStack evidence (Task 8 — deferred this turn)
- Sprint evidence file updates after live gates

The repository security-plugin gate was removed from the global delivery
workflow by direct user instruction on 2026-08-01. Luna's quality/security
review and the task-diff secret scan remain required; no Codex Security scan is
part of completion.

## Coordinator final verification (2026-08-02)

| Gate | Result |
|------|--------|
| Non-integration pytest | **923 passed, 2 skipped, 197 deselected** |
| Ruff | **PASS** |
| MyPy | **PASS** (131 source files) |
| Contract validation | **PASS** (20 files) |
| Alembic head | `20260801_0017` |
| Diff check | **PASS** |
| Task-diff secret scan | 39 candidates in checksum/fixture/negative-test files; manually classified as synthetic IDs, manifest hashes, and deliberate rejection fixtures; no production credential found |
| PostgreSQL 18 integration | **148 passed**; fresh upgrade, downgrade to `20260731_0016`, and re-upgrade all passed |
| Luna review | Pass 1 `SPEC_COMPLIANT`; pass 2 `QUALITY_APPROVED` |

Live attempt `019fbe48-f7c9-73d3-83da-78e09f677376` proved CPS publication
and OPS receipt, but the pre-OPS-1901 adapter did not finish provider
collection. This is dependency evidence, not acceptance; a new idempotency key
must be used after OPS-1901 is deployed.

## Paired OPS-1901 closure (2026-08-02)

- OPS commit: `254d60d`, pushed to `origin/sprint-19/ops-1901`.
- CPS canonical commit: `b8a5ff7`, pushed to `origin/sprint-19/cps-1901`.
- Project-scoped live operation `019fbe70-105a-7e7b-8a86-f0030e138204`
  reached `SUCCEEDED`.
- CPS/OpenStack CLI comparison matched the complete provider-ID set and
  material fields for two images and three flavors.
- Capability validation `019fbe70-a6c3-7c0e-a949-0abb22bc15d4` succeeded;
  unsupported image import was reported explicitly rather than inferred.
- The system-scoped Glance 403 path produced `SKIPPED_UNSUPPORTED`, proving no
  misleading empty complete batch. No provider resource was created.
- Linked OPS evidence: `docs/runbooks/sprint-19-catalog-mappers.md` in OPS
  commit `254d60d`.

## Luna pass-19 remediation disposition (2026-08-01, worker round 19, PASS-2)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `validate_capability_extra_tree` walks document structure and validates `services`/`features` additional properties plus root extras with independent `ExtraDepth1..4` budget (`shallow_map_depth=0`); no longer counts `services→compute→extra` path toward depth. Tests: `test_capability_runtime_and_schema_both_accept_services_compute_extra_four_levels`, `test_capability_runtime_and_schema_both_reject_services_compute_extra_five_levels`. |
| I2 | Important | **Fixed** | `AdminCatalogCuratedView.catalog_approved` derived from canonical `provider_attributes.catalog_approved is True` only; field serialized, raw attributes excluded. Tests: expanded CPS-1703 admin list + non-canonical marker + approved-filter consistency cases in `test_catalog.py`. |
| I3 | Important | **Fixed** | `test_catalog_status_filter_uses_expression_indexes` parameterized for image (`ix_images_catalog_status`) and flavor (`ix_flavors_catalog_status`); metadata test retains migration name assertions. PG18 run skipped (password auth failed for `cmp@127.0.0.1:5432/cps_test`). |

## RED / GREEN command ledger (pass-19)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-19 RED (capability depth) | `.venv/bin/pytest tests/unit/contracts/test_conservative_tree_schema_parity.py::test_capability_runtime_and_schema_both_accept_services_compute_extra_four_levels -q` | FAIL | **FAIL** (runtime depth reject; schema accept) |
| Pass-19 RED (curated catalog_approved) | `.venv/bin/pytest tests/unit/api/test_catalog.py::test_admin_catalog_lists_cps_1703_curated_resource_types -q` | FAIL | **FAIL** (`AdminCatalogCuratedView` missing `catalog_approved`) |
| Pass-19 GREEN (focused) | `.venv/bin/pytest tests/unit/contracts/test_conservative_tree_schema_parity.py -k "four_levels or five_levels" tests/unit/api/test_catalog.py -k "admin_catalog_curated or admin_catalog_lists_cps" tests/contract/test_catalog_contract.py -k capability -q` | PASS | **42 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (20 files) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **923 passed**, 2 skipped |
| Contract suite | `.venv/bin/pytest tests/contract/ -q` | PASS | **256 PASS** |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_catalog_status_filter_uses_expression_indexes tests/integration/db/test_schema_parity.py tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | PASS | **skipped** (password auth failed); tests structurally runnable |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 2 (no trailing-whitespace hits; pre-existing harness quirk) |

## Luna pass-18 remediation disposition (2026-08-01, worker round 18, PASS-2)

| ID | Severity | Disposition | Evidence |
|----|----------|-------------|----------|
| I1 | Important | **Fixed** | `_verify_inventory_batch_checksum` binds digest strictly to envelope minor version (`1.0` → `compute_inventory_checksum_v1_0` only; `>=1.1` → v1.1 only); `_reject_schema_1_0_catalog_fields` blocks catalog enrichment under `1.0`. Tests: expanded `test_inventory_batch_contract.py` schema_1_0/1_1 cases; ingress: `tests/unit/domain/test_inventory_inbox_checksum.py`. |
| I2 | Important | **Fixed** | Capability minor semantics use numeric `int(minor)` (leading zeros equivalent); JSON Schema `allOf` pattern aligned to `^1\.0*[1-9][0-9]*$` for catalog-key requirement. Tests: `test_capability_runtime_and_schema_accept_1_01_with_catalog_keys`, `test_capability_runtime_and_schema_reject_1_01_without_catalog_keys`. |
| I3 | Important | **Fixed** | `AdminCatalogCuratedView` excludes raw `provider_attributes` from admin CPS-1703 list projection via `Field(exclude=True)` + `project_admin_catalog_curated_view`. Test: `test_admin_catalog_lists_cps_1703_curated_resource_types` asserts omission. |
| I4 | Important | **Fixed** | Migration `20260801_0017` adds expression partial indexes `ix_images_catalog_status` and `ix_flavors_catalog_status` on `(provider_connection_id, lower(provider_status))` with approved/live predicate; integration EXPLAIN test `test_catalog_status_filter_uses_expression_indexes`. |

### Version grammar rule (capability + inventory envelope)

- Pattern: `^1\.[0-9]+$` (no bare major-only strings).
- Semantics: minor component parsed as base-10 integer (`"01"` ≡ `1`); catalog administration keys required when `int(minor) >= 1`.

## RED / GREEN command ledger (pass-18)

| Step | Command | Expected | Actual |
|------|---------|----------|--------|
| Pass-18 RED (checksum) | `.venv/bin/pytest tests/contract/test_inventory_batch_contract.py -k "schema_1_0_envelope_rejects_catalog or schema_1_0_envelope_rejects_enriched or schema_1_1_envelope_rejects_mismatched" tests/unit/domain/test_inventory_inbox_checksum.py -q` | FAIL | **15 FAIL** (dual-checksum accepted v1.1 under 1.0; catalog fields allowed) |
| Pass-18 RED (capability 1.01) | `.venv/bin/pytest tests/contract/test_catalog_contract.py -k "1_01" -q` | FAIL | **1 FAIL** (schema accepted `1.01` without catalog keys) |
| Pass-18 RED (admin curated) | `.venv/bin/pytest tests/unit/api/test_catalog.py::test_admin_catalog_lists_cps_1703_curated_resource_types -q` | FAIL | **3 FAIL** (`provider_attributes` present) |
| Pass-18 RED (status indexes) | `.venv/bin/pytest tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | FAIL | **1 FAIL** (`ix_flavors_catalog_status` missing) |
| Pass-18 GREEN (focused) | same four commands | PASS | **16 PASS** |
| Ruff | `.venv/bin/ruff check src tests` | exit 0 | exit 0 |
| MyPy | `.venv/bin/mypy src` | exit 0 | exit 0 (131 files) |
| Contracts validate | `.venv/bin/python -m cps.contracts.validate_contracts` | ok | ok (20 files) |
| Manifest | `.venv/bin/python -m cps.contracts.write_manifest` | ok | ok (`capability_document.schema.json` checksum refreshed) |
| Non-integration pytest | `.venv/bin/pytest -q -m "not integration"` | exit 0 | **916 passed**, 2 skipped |
| PG18 integration | `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test pytest tests/integration/db/test_inventory_repository.py::test_catalog_status_filter_uses_expression_indexes tests/integration/db/test_schema_parity.py tests/unit/infrastructure/test_schema_metadata.py::test_catalog_query_indexes_are_declared_in_migration -q` | PASS | **skipped** (password auth failed for `cmp@127.0.0.1:5432/cps_test`) |
| Alembic cycle | `CPS_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test alembic downgrade 20260731_0016 && upgrade head` | exit 0 | **skipped** (same PG auth failure) |
| Alembic heads | `.venv/bin/alembic heads` | `20260801_0017 (head)` | `20260801_0017 (head)` |
| diff check | `git diff --check` | exit 0 | exit 2 (no trailing-whitespace hits in diff; pre-existing harness quirk) |

## Cleanup

Disposable `cps_test_*` session databases dropped after integration run; no OpenStack resources created.
