# CPS-1901 Catalog Detail and Compatibility Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Task ID:** CPS-1901

**Goal:** Deliver provider-neutral image/flavor list, detail, filter, and compatibility contracts while preserving the approved-only member catalog and separating full administrator inventory.

**Architecture:** CPS remains the canonical contract and PostgreSQL source of truth. Add additive inventory fields to the version-1 contract, persist queryable fields in the existing typed image/flavor columns, retain bounded non-query metadata in `provider_attributes`, and expose purpose-specific member/admin projections. A framework-independent compatibility service evaluates persisted image/flavor snapshots; it performs no provider I/O.

**Tech Stack:** CPython 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 18, pytest, Ruff, MyPy, RabbitMQ contract fixtures.

## Approved Inputs and Context

- Sprint/design approval for CPS-1901 and paired OPS-1901 is granted by the user on 2026-08-01.
- Authoritative repository rules: `AGENTS.md`.
- Canonical designs:
  - `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`
  - `docs/superpowers/specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`
  - `docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`
- Delivery policy: `plan/README.md`, `plan/product-backlog.md`, `docs/ai/vibe-coding-workflow.md`, and `docs/ai/review-checklists.md`.
- Active work packet: `plan/sprints/sprint-19.md` and `plan/tasks/sprint-19/CPS-1901-catalog-contracts.md`.
- Predecessor policy: `plan/sprints/sprint-17.md` and `plan/tasks/sprint-17/CPS-1703-curated-catalog-policy.md`.
- Behavioral references only:
  - `../opensource/horizon/openstack_dashboard/api/glance.py`
  - `../opensource/horizon/openstack_dashboard/api/nova.py`
  - `../opensource/horizon/openstack_dashboard/dashboards/project/images/images/tables.py`
  - `../opensource/horizon/openstack_dashboard/dashboards/admin/images/tables.py`
  - `../opensource/horizon/openstack_dashboard/dashboards/admin/flavors/tables.py`
- CodeGraph blast radius:
  - `Flavor` and `Image` persistence flow through `InventoryRepository._upsert_resource`.
  - Catalog reads depend on `InventoryRepository.list_catalog_resources`, `catalog_resource_is_approved`, `cps.api.routers.catalog`, and the instance/volume policy consumers.
  - OPS producer work is paired under OPS-1901; CPS does not import OpenStackSDK or Horizon code.
- Initial worktrees are clean at `81c1b02` (CPS) and `b843029` (OPS). Recheck before execution.

## Acceptance Criteria

1. Canonical full/minimal image and flavor inventory fixtures validate in CPS and the pinned OPS copy.
2. Version `1.1` is additive to major version `1`; `1.x` consumers tolerate approved additive fields and unknown major versions fail safely.
3. Image detail includes owner project ID, status, protection, container/disk format, size, virtual size, tags, bounded properties, checksum, minimum disk/RAM, visibility, and approval.
4. Flavor detail includes vCPUs, RAM, root/ephemeral disk, swap, public/enabled state, bounded extra specs, project access IDs, and approval.
5. Image/flavor list endpoints support stable pagination and filters for name, status, visibility/public, owner/project, disk format, minimum/maximum size, minimum disk/RAM, and approval where authorized.
6. Member catalog list/detail returns only approved, live, scope-visible resources and never returns raw `provider_attributes`.
7. Administrator list/detail uses the admin dependency and can inspect approved/unapproved, stale, and soft-deleted inventory without weakening member policy.
8. Compatibility checks fail closed for stale/unapproved/inactive resources, non-launchable formats, provider/project scope mismatch, incomplete dimensions, and flavor RAM/root disk below image minima.
9. Compatibility reason codes are deterministic and independently testable for launch, rebuild, resize, and volume-from-image consumers.
10. Repository ordering is deterministic (`name`, then CPS `id`), filter predicates are indexed, and an incomplete/failed sync never changes deletion semantics.
11. OpenAPI exposes the specialized request/response schemas and the admin/member route separation.
12. Focused/full gates, independent review, task-diff secret scan, live CPS/OpenStack comparison, redacted runbook, and Git authorization gates pass.

## Out of Scope

- Image/flavor create, update, delete, import, upload, member mutation, access mutation, deactivate, or reactivate; those belong to CPS-1902/CPS-1903.
- Image bytes, source credentials, signed URLs, direct URLs, Glance locations, tokens, or raw provider bodies.
- Integrating compatibility checks into launch/rebuild/resize/volume handlers; CPS-1904 owns consumer wiring.
- Cursor pagination, a shared contracts package, provider release-name checks, Horizon/Django/client imports, or new runtime dependencies.
- Physical deletion of stale inventory or changes to full-sync finalization.
- TMS/LMS/BMS/VMware changes.

## Contract and Compatibility Decisions

### Security amendment: deferred tenant authorization

CPS-1203 remains deferred and the current authenticated principal has no
authoritative organization/workspace membership claim. CPS-1901 therefore must
not infer tenant access from client-supplied `org_id`, `workspace_id`, project
IDs, connection IDs, READY bindings, or project-scoped connections.

- Member list/detail exposes only approved, live `public` or `community` images
  and approved, enabled public flavors.
- Private/shared images and private flavors remain visible only through the
  administrator projection until CPS-1203 activates the fail-closed TMS
  authorization port.
- Member catalog and compatibility endpoints accept no org/workspace/project
  scope selector. Restricted or unknown provider resource IDs produce the same
  non-enumerating outcome; reason codes must not reveal approval, lifecycle, or
  tenant-scope state for inaccessible resources.
- Admin filters and detail retain bounded project/member/access information for
  administration and later lifecycle stories.

This is a deliberate fail-closed limitation, not permission to implement or
simulate TMS authorization in Sprint 19.

### Version decision

- Keep major version `1`; emit `schema_version: "1.1"` for enriched inventory/capability fixtures.
- All new inventory fields are optional so existing `1.0` producers remain valid during coordinated rollout.
- Pydantic models continue rejecting unknown top-level fields where the inventory payload requires exactness; the CPS and OPS copies are updated in the same sprint before live use.
- Unknown major versions remain rejected before persistence. No dual incompatible payload is served under the same version.
- CPS canonical artifacts are updated first; OPS-1901 copies fixture/schema bytes and pins the resulting CPS manifest exactly.

### Canonical field map

| Contract field | CPS storage/projection | Bounds and semantics |
|---|---|---|
| `provider_resource_id`, `name` | Existing common typed columns | 1..255 characters |
| `provider_status` | Existing common typed column | Image status normalized lowercase for comparisons; preserved provider value in API |
| `project_provider_resource_id` | Existing image owner typed column | Nullable, 255 characters; flavor remains provider-global |
| `vcpus` | `Flavor.vcpus` | Integer 0..4096 |
| `ram_mib` | `Flavor.ram_mib` | Integer 0..16,777,216 |
| `root_disk_gib` | `Flavor.root_disk_gib` | Integer 0..1,048,576 |
| `ephemeral_disk_gib` | `Flavor.ephemeral_disk_gib` | Integer 0..1,048,576 |
| `swap_mib` | `Flavor.swap_mib` | Integer 0..16,777,216; unusual numeric strings normalize in OPS |
| `is_public`, `enabled` | Existing flavor typed columns | Nullable booleans; `enabled=false` is not live |
| `visibility` | `Image.visibility` | `public`, `private`, `shared`, or `community` |
| `size_bytes` | `Image.size_bytes` | Integer 0..9,223,372,036,854,775,807 |
| `min_disk_gib` | `Image.min_disk_gib` | Integer 0..1,048,576 |
| `min_ram_mib` | `Image.min_ram_mib` | Integer 0..16,777,216 |
| `disk_format` | `Image.disk_format` | Lowercase, 1..32 characters |
| `checksum` | `Image.checksum` | Nullable, at most 128 characters |
| `catalog_approved` | Bounded `provider_attributes` plus dedicated projection | Boolean only; missing/malformed is false |
| `is_protected`, `container_format`, `virtual_size_bytes` | Bounded `provider_attributes` | Boolean/string/nonnegative integer |
| `tags` | Bounded `provider_attributes` | At most 64 strings, each at most 255 characters |
| `properties`, `extra_specs` | Bounded `provider_attributes` | Conservative shared tree: map depth 4, nested map/list entries 4, string 128 chars; root map 128 entries; explicit runtime serialized 64 KiB check |
| `access_project_ids` | Bounded flavor `provider_attributes` | Sorted unique project IDs, at most 256 entries, each at most 255 characters |

Query fields stay in existing typed columns. No new typed data column is justified. Add index-only migration `20260801_0017_catalog_query_indexes.py`; use JSONB containment for `catalog_approved` so malformed legacy JSON cannot cause a cast failure.

### API decision

- Member, approved-only:
  - `GET /api/v1/provider-connections/{connection_id}/catalog`
  - `GET /api/v1/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}`
  - `POST /api/v1/catalog/compatibility`
- Administrator, full inventory:
  - `GET /api/v1/admin/provider-connections/{connection_id}/catalog`
  - `GET /api/v1/admin/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}`
- `resource_type` is restricted to `image|flavor` in this story.
- Member responses use `CatalogImageSummary`/`CatalogFlavorSummary`; admin responses use `CatalogImageDetail`/`CatalogFlavorDetail`.
- Member routes force `approved=true`, `include_deleted=false`, `lifecycle_state=ACTIVE`, and project visibility. Supplying admin-only query parameters returns `422`.
- Admin routes accept `approved=true|false`, omission for either value, and `include_deleted`; detail returns normalized bounded fields, never raw `provider_attributes`.
- Existing generic member inventory endpoints reject `image` and `flavor` with a normalized not-found response, preventing bypass of the curated route. Other resource families remain unchanged.

### Filter decision

Common filters: `name`, `status`, `approved`, `page|offset`, `limit`, `sort=name|created_at|updated_at`, and `order=asc|desc`.

Catalog list pagination resolves `page` or legacy `offset` to a repository offset capped at **`MAX_CATALOG_OFFSET = 100_000`**; requests whose resolved offset exceeds this value return normalized **`422 VALIDATION_FAILED`**.

Image-only filters: `visibility`, `is_public` (alias mapped to visibility), `owner_project_id`, `disk_format`, `size_min_bytes`, `size_max_bytes`, `min_disk_gib`, and `min_ram_mib`.

Flavor-only filters: `is_public`, `min_root_disk_gib`, `min_ram_mib`, and `project_access_id`.

Invalid enum values, negative sizes, inverted ranges, overlong values, and filters for the wrong resource type return normalized `422 VALIDATION_FAILED`. Sorting always appends CPS `id` in the same direction.

### Compatibility decision

Add these exact interfaces in `src/cps/application/catalog_compatibility.py`:

```python
class CatalogUse(StrEnum):
    LAUNCH = "LAUNCH"
    REBUILD = "REBUILD"
    RESIZE = "RESIZE"
    VOLUME_FROM_IMAGE = "VOLUME_FROM_IMAGE"

class CompatibilityReason(StrEnum):
    IMAGE_NOT_FOUND = "IMAGE_NOT_FOUND"
    FLAVOR_NOT_FOUND = "FLAVOR_NOT_FOUND"
    IMAGE_NOT_APPROVED = "IMAGE_NOT_APPROVED"
    FLAVOR_NOT_APPROVED = "FLAVOR_NOT_APPROVED"
    IMAGE_NOT_LIVE = "IMAGE_NOT_LIVE"
    FLAVOR_NOT_LIVE = "FLAVOR_NOT_LIVE"
    IMAGE_FORMAT_NOT_LAUNCHABLE = "IMAGE_FORMAT_NOT_LAUNCHABLE"
    IMAGE_SCOPE_MISMATCH = "IMAGE_SCOPE_MISMATCH"
    FLAVOR_SCOPE_MISMATCH = "FLAVOR_SCOPE_MISMATCH"
    CATALOG_DATA_INCOMPLETE = "CATALOG_DATA_INCOMPLETE"
    FLAVOR_RAM_BELOW_IMAGE_MINIMUM = "FLAVOR_RAM_BELOW_IMAGE_MINIMUM"
    FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM = "FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM"

def evaluate_catalog_compatibility(
    *,
    use: CatalogUse,
    image: CatalogImageSnapshot | None,
    flavor: CatalogFlavorSnapshot | None,
    provider_connection_id: UUID,
    project_provider_resource_id: str,
) -> CatalogCompatibilityResult: ...
```

- `LAUNCH`, `REBUILD`, and `RESIZE` require both image and flavor.
- `VOLUME_FROM_IMAGE` requires image only and skips flavor dimension checks.
- Live image means inventory lifecycle `ACTIVE` and provider status `active`.
- Live flavor means inventory lifecycle `ACTIVE` and `enabled is not False`.
- Launchable image requires a nonempty disk/container format, rejects `aki`, `ari`, and Docker containers, and never infers support from an OpenStack release name.
- Member image scope permits only `public`/`community`; `private` and `shared`
  fail closed until CPS-1203 is active.
- Member flavor scope permits only public flavors; private flavors fail closed
  until CPS-1203 is active.
- Any resource from another provider connection fails scope.
- Reason codes are unique and returned in enum declaration order; `compatible` is true only when the reason list is empty.

## Threat Model and Security Scope

### Assets and trust boundaries

- Assets: administrator-only inventory, project ownership, approval policy, canonical contracts/checksums, compatibility decisions, and secret-free operational evidence.
- Boundaries: member JWT to member API, admin JWT to admin API, OPS inventory message to CPS validation, JSON payload to PostgreSQL, and CPS result to clients/runbook.
- Attacker-controlled inputs: API filters/IDs, inventory metadata/tags/properties/extra specs/access IDs, schema versions, malformed JSON, and stale/replayed batches.

### Required invariants

- Member callers cannot enumerate unapproved, deleted, cross-provider, or cross-project resources.
- Admin and member dependencies remain distinct; admin tokens are not silently accepted on member routes under current role policy.
- Approval is a server-derived boolean; request payloads cannot set it.
- No password, token, authorization header, private key, `user_data`, CA material, credential-bearing URL, signed URL, raw catalog, raw response, or SDK object reaches a contract, database metadata value, log, fixture, exception, or runbook.
- Metadata limits are enforced before persistence and before response serialization.
- Failed/partial inventory never causes deletion and targeted errors other than provider-confirmed 404 never create tombstones.
- Compatibility checks fail closed on missing, stale, malformed, or scope-ambiguous data.

### Abuse cases to test

- Member calls admin detail or adds `include_deleted=true`/`approved=false`.
- Cross-provider CPS UUID/provider ID substitution.
- Private/shared image and private flavor access bypass.
- Secret-bearing key at nested depth and signed/tokenized URL value.
- Oversized map/list/string, excessive nesting, duplicate access IDs, negative/overflow dimensions.
- Unknown major contract, additive minor field, duplicate batch with changed checksum.
- JSON approval values `"true"`, `1`, object, or missing instead of boolean `true`.
- Soft-deleted/stale image or flavor selected for compatibility.
- Name wildcards and very large limits used for query amplification.

Unresolved Critical/High findings block live acceptance, completion, commit, and push.

## Exact File Scope

### Production and contract files

- Modify: `src/cps/contracts/messages/inventory.py`
- Create: `src/cps/contracts/safe_metadata.py`
- Modify: `src/cps/contracts/validation.py`
- Create: `src/cps/contracts/jsonschema/inventory_batch.schema.json`
- Create: `src/cps/contracts/fixtures/events/inventory_batch_image_full.json`
- Create: `src/cps/contracts/fixtures/events/inventory_batch_image_minimal.json`
- Create: `src/cps/contracts/fixtures/events/inventory_batch_flavor_full.json`
- Create: `src/cps/contracts/fixtures/events/inventory_batch_flavor_minimal.json`
- Modify: `src/cps/contracts/jsonschema/capability_document.schema.json`
- Modify: `src/cps/contracts/checksums.json`
- Modify: `src/cps/api/schemas/catalog.py`
- Modify: `src/cps/api/schemas/inventory.py`
- Modify: `src/cps/api/routers/catalog.py`
- Modify: `src/cps/api/routers/inventory.py`
- Modify: `src/cps/main.py`
- Create: `src/cps/application/catalog_compatibility.py`
- Modify: `src/cps/infrastructure/db/repositories/inventory.py`
- Create: `alembic/versions/20260801_0017_catalog_query_indexes.py`

### Test files

- Modify: `tests/contract/test_inventory_batch_contract.py`
- Modify: `tests/contract/test_connection_validation_contract.py`
- Modify: `tests/contract/test_catalog_contract.py`
- Modify: `tests/contract/test_contract_manifest.py`
- Modify: `tests/unit/api/test_catalog.py`
- Modify: `tests/unit/api/test_route_normalization.py`
- Create: `tests/unit/application/test_catalog_compatibility.py`
- Modify: `tests/integration/db/test_inventory_repository.py`
- Modify: `tests/integration/db/test_schema_parity.py`
- Modify: `tests/unit/infrastructure/test_schema_metadata.py`
- Create: `tests/unit/infrastructure/db/test_inventory_operation_result_validation.py`

### Completion evidence

- Create at completion: `docs/runbooks/sprint-19-catalog-contracts.md`
- Modify at completion: `plan/tasks/sprint-19/CPS-1901-catalog-contracts.md`
- Modify at completion: `plan/sprints/sprint-19.md`

No dependency or lockfile changes are expected. Any file outside this list requires explicit re-planning before modification.

---

### Task 1: Isolated Worktree and Baseline

**Files:** No tracked file changes.

**Interfaces:** Establishes the clean execution base for every later task.

- [ ] **Step 1: Invoke execution isolation**

Invoke `superpowers:using-git-worktrees`, then create a CPS-1901 worktree and task branch without touching the current checkout.

- [ ] **Step 2: Recheck repository state**

Run:

```bash
rtk git status --short
rtk git log -5 --oneline
```

Expected: no untracked/modified files in the new worktree; HEAD contains the approved Sprint 19 planning commit.

- [ ] **Step 3: Invoke the execution workflow**

Invoke `superpowers:subagent-driven-development` (preferred) or `superpowers:executing-plans`, then invoke `superpowers:test-driven-development` before the first code change.

- [ ] **Step 4: Record baseline gates**

Run:

```bash
rtk pytest -q tests/contract/test_catalog_contract.py tests/contract/test_inventory_batch_contract.py tests/unit/api/test_catalog.py
rtk ruff check src tests
rtk mypy src
```

Expected: baseline passes. Stop and diagnose any unrelated failure instead of weakening tests.

### Task 2: Canonical Additive Inventory Contract

**Files:**
- Modify: `src/cps/contracts/messages/inventory.py`
- Create: four full/minimal image/flavor fixtures listed above
- Create: `src/cps/contracts/jsonschema/inventory_batch.schema.json`
- Modify: `src/cps/contracts/jsonschema/capability_document.schema.json`
- Modify: `src/cps/contracts/checksums.json`
- Modify: `tests/contract/test_inventory_batch_contract.py`
- Modify: `tests/contract/test_catalog_contract.py`
- Modify: `tests/contract/test_contract_manifest.py`

**Interfaces:**
- Produces optional `InventoryBatchItem` image/flavor fields from the field map.
- Produces capability keys `image.import`, `image.member`, `image.deactivate`, `image.reactivate`, `flavor.create`, `flavor.delete`, `flavor.access`, and `flavor.extra_specs`.
- OPS-1901 consumes byte-identical fixtures/schema and the regenerated manifest.

- [ ] **Step 1: Write RED contract tests**

Add exact assertions for full/minimal image/flavor payloads, `schema_version="1.1"`, additive minor acceptance, unknown major rejection, visibility/status enums, nonnegative dimensions, metadata bounds, secret-bearing keys/values, and deterministic checksums.

- [ ] **Step 2: Observe RED**

Run:

```bash
rtk pytest -q tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/contract/test_contract_manifest.py
```

Expected: FAIL because the enriched fields, fixtures, inventory JSON Schema, capability requirements, and manifest entries do not exist.

- [ ] **Step 3: Implement minimal GREEN contract**

Add only the optional fields and validators in the approved field map. Centralize bounds/sanitization validation; do not permit raw metadata or secret-bearing values. Generate the inventory JSON Schema from the canonical Pydantic model, write the four synthetic fixtures, and require the eight capability keys.

- [ ] **Step 4: Regenerate and verify manifest**

Run:

```bash
python -m cps.contracts.write_manifest
python -m cps.contracts.validate_contracts
rtk pytest -q tests/contract/test_inventory_batch_contract.py tests/contract/test_catalog_contract.py tests/contract/test_contract_manifest.py
```

Expected: manifest reports success and focused contract tests PASS.

- [ ] **Step 5: Refactor while GREEN**

Remove duplicate validator constants only when both image and flavor models use them; rerun the focused contract command after each refactor.

- [ ] **Step 6: Prepare commit boundary**

Prepare, but do not execute, proposal:

```text
feat(cps): define enriched catalog inventory contracts
```

Include only Task 2 files.

### Task 3: Persist Existing Typed Fields and Add Query Indexes

**Files:**
- Modify: `src/cps/infrastructure/db/repositories/inventory.py`
- Create: `alembic/versions/20260801_0017_catalog_query_indexes.py`
- Modify: `tests/integration/db/test_inventory_repository.py`
- Modify: `tests/integration/db/test_schema_parity.py`
- Modify: `tests/unit/infrastructure/test_schema_metadata.py`

**Interfaces:**
- Consumes enriched `InventoryBatchItem`.
- Produces typed image/flavor rows plus bounded provider attributes.
- Produces indexed `list_catalog_resources(...)` and `get_catalog_resource(...)` repository APIs.

- [ ] **Step 1: Write RED persistence tests**

Cover full/minimal upsert, refresh replacing provider metadata without erasing canonical project linkage, approval JSON containment, every filter, stable tie-breaking, stale/deleted behavior, detail 404, and `EXPLAIN` use of the intended indexes on representative seeded data.

- [ ] **Step 2: Observe RED**

Run:

```bash
CPS_RUN_INTEGRATION=1 rtk pytest -q tests/integration/db/test_inventory_repository.py tests/integration/db/test_schema_parity.py tests/unit/infrastructure/test_schema_metadata.py
```

Expected: FAIL because flavor/image fields are not promoted by `_upsert_resource`, filter methods/signatures are absent, and catalog indexes do not exist.

- [ ] **Step 3: Implement minimal typed persistence**

Promote the existing Flavor/Image columns during insert and conflict update. Keep only approved bounded non-query metadata in `provider_attributes`. Add resource-specific predicates through explicit allow-listed filter dataclasses; never interpolate column or operator names from input.

- [ ] **Step 4: Implement index-only migration**

Create:

```text
ix_images_catalog_approved_name
ix_flavors_catalog_approved_name
ix_images_catalog_filters
ix_images_catalog_owner
ix_flavors_catalog_filters
```

Use PostgreSQL partial predicates with `provider_attributes @> '{"catalog_approved": true}'::jsonb`, `lifecycle_state <> 'DELETED'`, and the typed columns named in the filter decision. Downgrade drops only these indexes.

- [ ] **Step 5: Verify migration lifecycle**

Run on disposable PostgreSQL 18:

```bash
rtk alembic upgrade head
rtk alembic downgrade 20260731_0016
rtk alembic upgrade head
```

Expected: each command exits 0; `20260801_0017` is the single head after re-upgrade; no table/column data is rewritten.

- [ ] **Step 6: Verify GREEN**

Rerun the Task 3 focused tests.

Expected: PASS, including stable ordering and query-plan assertions.

- [ ] **Step 7: Prepare commit boundary**

Prepare, but do not execute, proposal:

```text
feat(cps): persist and index catalog detail fields
```

Include only Task 3 files.

### Task 4: Member/Admin Catalog List and Detail APIs

**Files:**
- Modify: `src/cps/api/schemas/catalog.py`
- Modify: `src/cps/api/schemas/inventory.py`
- Modify: `src/cps/api/routers/catalog.py`
- Modify: `src/cps/api/routers/inventory.py`
- Modify: `src/cps/main.py`
- Modify: `tests/unit/api/test_catalog.py`
- Modify: `tests/unit/api/test_route_normalization.py`

**Interfaces:**
- Consumes repository catalog filter/detail APIs.
- Produces specialized member/admin OpenAPI projections and route dependencies.

- [ ] **Step 1: Write RED API tests**

Test every common/resource-specific filter, `page` and legacy `offset`, stable pagination metadata, member approved/live/project visibility, admin unapproved/deleted visibility, member rejection of admin-only parameters, member generic inventory bypass rejection, admin/member 401/403, detail success, cross-connection 404, soft-deleted 404 for members, and bounded response fields.

- [ ] **Step 2: Observe RED**

Run:

```bash
rtk pytest -q tests/unit/api/test_catalog.py tests/unit/api/test_route_normalization.py tests/unit/security/auth/test_middleware.py
```

Expected: FAIL because specialized routes, projections, filters, and bypass protection are absent.

- [ ] **Step 3: Implement minimal schemas and routes**

Split `member_router` and `admin_router`; register them under existing prefix constants. Use `require_member` and `require_admin` dependencies explicitly. Convert rows through specialized models and never serialize `provider_attributes` directly.

- [ ] **Step 4: Verify OpenAPI and GREEN**

Run the Task 4 focused tests and:

```bash
python - <<'PY'
from cps.main import create_app
schema = create_app().openapi()
required = {
    "/api/v1/provider-connections/{connection_id}/catalog",
    "/api/v1/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
    "/api/v1/admin/provider-connections/{connection_id}/catalog",
    "/api/v1/admin/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
}
missing = required.difference(schema["paths"])
assert not missing, sorted(missing)
PY
```

Expected: focused tests PASS and no required path is missing.

- [ ] **Step 5: Refactor while GREEN**

Extract shared filter parsing only if member/admin handlers both use it; keep authorization and projection choices visibly separate.

- [ ] **Step 6: Prepare commit boundary**

Prepare, but do not execute, proposal:

```text
feat(cps): expose separated catalog list and detail APIs
```

Include only Task 4 files.

### Task 5: Provider-Neutral Compatibility Service

**Files:**
- Create: `src/cps/application/catalog_compatibility.py`
- Modify: `src/cps/api/schemas/catalog.py`
- Modify: `src/cps/api/routers/catalog.py`
- Create: `tests/unit/application/test_catalog_compatibility.py`
- Modify: `tests/unit/api/test_catalog.py`

**Interfaces:**
- Consumes persisted catalog snapshots by provider identity.
- Produces `CatalogCompatibilityResult(compatible, reason_codes)` for later CPS-1904 consumers and the member read endpoint.

- [ ] **Step 1: Write RED compatibility table tests**

Use a parameterized matrix covering every exact reason code, multiple simultaneous reasons, deterministic ordering, public/private/shared/community scope, active/deactivated/deleted states, Docker/raw and AKI/ARI cases, zero/minimum dimensions, volume-from-image without a flavor, and cross-provider references.

- [ ] **Step 2: Observe RED**

Run:

```bash
rtk pytest -q tests/unit/application/test_catalog_compatibility.py tests/unit/api/test_catalog.py
```

Expected: FAIL because the service, request/result models, and endpoint are absent.

- [ ] **Step 3: Implement minimal pure evaluation**

Implement the exact interface and reason enum from this plan. Keep it independent of FastAPI, SQLAlchemy, and OpenStack concepts beyond normalized field values. The router loads both resources through the repository and passes immutable snapshots to the pure function.

- [ ] **Step 4: Verify GREEN**

Rerun Task 5 tests.

Expected: PASS with exact reason-code lists and normalized API envelope.

- [ ] **Step 5: Refactor while GREEN**

Replace repeated reason appends with small named predicates only when the tests keep one-to-one traceability from rule to reason.

- [ ] **Step 6: Prepare commit boundary**

Prepare, but do not execute, proposal:

```text
feat(cps): evaluate catalog compatibility deterministically
```

Include only Task 5 files.

### Task 5A: Security Amendment RED-GREEN Closure

**Files:** CPS-1901 catalog contract, schema, router, repository, compatibility,
migration, tests, and runbook files already listed above.

- [ ] Add RED tests proving member routes accept no org/workspace/project scope,
  expose only public/community images and public flavors, and return a uniform
  non-enumerating result for private/shared/unapproved/stale/unknown IDs.
- [ ] Add RED tests for PEM private keys, `privateKey` variants, signed or
  credential URLs nested in lists, metadata/attachments/attributes depth and
  64-KiB bounds, and equivalent JSON Schema rejection.
- [ ] Add RED tests that missing image minima fail closed, legacy response
  projections enforce 255-character/list/64-KiB bounds, name filtering treats
  `%` and `_` literally, and member `approved` query parameters return `422`.
- [ ] Implement the minimum fail-closed member query/compatibility projection,
  recursive secret/bounds validator, schema constraints, literal escaped name
  predicate, and query validation needed to make those tests GREEN.
- [ ] Run focused tests, PostgreSQL 18 EXPLAIN/index evidence, full deterministic
  gates, review, security scan, live comparison, cleanup, and runbook updates.

### Task 6: Independent Review and Review Remediation

**Files:** The complete CPS-1901 task diff only.

- [ ] **Step 1: Request independent review**

Invoke `superpowers:requesting-code-review`. Dispatch Codex ChatGPT 5.6 luna to review:

1. acceptance/spec/contract/checksum compliance; and
2. code quality, failure behavior, authorization, query safety, metadata bounds, compatibility math, migration/index safety, and tests.

Require severity plus file/line evidence.

- [ ] **Step 2: Receive findings rigorously**

Invoke `superpowers:receiving-code-review`. Reproduce or inspect every finding; reject unsupported findings with concrete evidence and fix valid findings through RED-GREEN-REFACTOR.

**Luna pass-19 Important remediation (2026-08-01, worker round 19, PASS-2):**

- `validate_capability_extra_tree` validates capability extras with per-subtree depth budget (`ExtraDepth1..4`) instead of counting document path depth; `services.compute.extra` four-level nested map accepted by runtime and JSON Schema; five-level rejected by both. Tests: `test_capability_runtime_and_schema_both_accept_services_compute_extra_four_levels`, `test_capability_runtime_and_schema_both_reject_services_compute_extra_five_levels`.
- `AdminCatalogCuratedView` exposes bounded boolean `catalog_approved` derived via `catalog_approved_from_attributes`; raw `provider_attributes` remain excluded. Tests: expanded `test_admin_catalog_lists_cps_1703_curated_resource_types`, `test_admin_catalog_curated_view_catalog_approved_is_false_for_non_canonical_marker`, `test_admin_catalog_curated_approved_filter_matches_catalog_approved_field`.
- Integration EXPLAIN coverage parameterized for both `ix_images_catalog_status` and `ix_flavors_catalog_status` (`test_catalog_status_filter_uses_expression_indexes`); migration index names unchanged in `20260801_0017` downgrade-safe drop list.

**Luna pass-18 Important remediation (2026-08-01, worker round 18, PASS-2 re-review):**

- Inventory checksum strictly bound to envelope `schema_version`: `1.0` accepts only `compute_inventory_checksum_v1_0` and rejects catalog enrichment fields; `>=1.1` accepts only v1.1 digest. Ingress regressions in `tests/unit/domain/test_inventory_inbox_checksum.py`.
- Capability minor version grammar: pattern `^1.[0-9]+$`, semantic minor `int(part)` (leading zeros equivalent); JSON Schema `allOf` uses `^1.0*[1-9][0-9]*$` parity with runtime catalog-key requirement.
- Admin CPS-1703 curated types use `AdminCatalogCuratedView` excluding serialized `provider_attributes`.
- Catalog status filters: expression partial indexes `ix_images_catalog_status` / `ix_flavors_catalog_status` on `lower(provider_status)`; EXPLAIN integration test `test_catalog_status_filter_uses_expression_indexes`.

**Luna pass-17 Important remediation (2026-08-01, worker round 17):**

- Inventory batch checksum dual-validation: `_verify_inventory_batch_checksum` accepts legacy schema `1.0` v1_0 digest from older OPS and canonical v1_1 digest; items always pass full `InventoryBatchItem` safety before checksum compare; inbox/semantic pass envelope `schema_version` via validation context. Tests: `test_legacy_schema_1_0_fixture_accepts_v1_0_checksum`, `test_schema_1_0_envelope_rejects_mismatched_legacy_checksum`, `test_schema_1_1_checksum_is_deterministic_and_distinct_from_wrong_digest`, `test_legacy_checksum_cannot_bypass_1_1_safety_validation`.
- Catalog pagination cap is opt-in: `resolve_catalog_pagination` applies `MAX_CATALOG_OFFSET`; legacy `resolve_pagination` uncapped for provider/connection/inventory/operation routes. Tests: `test_legacy_pagination_accepts_offset_above_catalog_max`, `test_catalog_offset_exceeding_maximum_is_rejected`.
- Admin catalog restores CPS-1703 curated types `network`, `volume-type`, `availability-zone` on admin list via `CatalogResourceType` + `InventoryResourceView` projection; member routes remain `CatalogStoryResourceType` image/flavor only. Tests: `test_admin_catalog_resource_type_enum_includes_cps_1703_curated_types`, `test_admin_catalog_lists_cps_1703_curated_resource_types`, `test_admin_catalog_rejects_image_filters_for_network_resource_type`.

**Luna pass-15 Important remediation (2026-08-01, worker round 15):**

- Inbox volume-attachment operation-result ingress must not coerce non-object non-null `resource` to `None`; reject before merge per `ResourceOperationResult`/`validate_volume_attachment_resource` with redacted `InventoryPersistenceError`. Tests: `test_apply_volume_attachment_result_rejects_non_object_resource`, `test_process_inbox_rejects_volume_attachment_non_object_resource_before_merge`.
- Python runtime and ECMA-262 JSON Schema reject letter-only `Bearer`/`Token` credentials with trailing whitespace or whitespace before punctuation (portable regex; adversarial safe names preserved). Test: expanded `test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials` (`Bearer abcdefgh `, `Token abcdefgh .`).

**Luna pass-14 Important remediation (2026-08-01, worker round 14):**

- Volume attachment operation results validate `resource` via `validate_volume_attachment_resource` before `InstanceVolume` merge; secret-bearing `device` values and unsupported fields fail with redacted `InventoryPersistenceError`. Test: `test_apply_volume_attachment_result_rejects_secret_bearing_resource`.
- Snapshot/instance operation-result upserts forward `provider_created_at`/`provider_updated_at` into canonical `_upsert_resource` items. Tests: `test_persist_snapshot_result_forwards_provider_timestamps_to_upsert`, `test_persist_instance_result_forwards_provider_timestamps_to_upsert`.
- `validate_provider_timestamp` rejects impossible calendar dates and out-of-range offsets at ingress (`ValueError` with stable messages); regex tightened runtime/schema. Tests: expanded `test_catalog_inventory_rejects_unsafe_or_unbounded_provider_timestamps`.
- Standalone letter-only `Bearer`/`Token` credentials rejected in runtime (`_STANDALONE_LETTER_ONLY_BEARER_TOKEN_PATTERN`) and portable JSON Schema with adversarial safe-name preserved. Tests: `test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials`.

**Luna pass-13 Critical/Important remediation (2026-08-01, worker round 13, CodeGraph blast-radius):**

- Canonicalize every inventory item in `_upsert_resource` via `canonicalize_inventory_item` / `InventoryBatchItem` (covers inbox operation-result and batch paths; image/flavor enriched fields included). Tests: `tests/unit/infrastructure/db/test_inventory_operation_result_validation.py`.
- Redact ownership conflicts: `OwnershipConflictError`, `PydanticCustomError`, stable repository error without raw owner values; `validate_safe_project_id` replaces ownership `str()` coercion. Tests: ownership contract + repository redaction cases.
- Persist bounded `provider_created_at`/`provider_updated_at` after canonical validation. Test: timestamp op-result case.
- Attachment worst-case proof: `AttachmentDepth4` leaf tier + `maxItems=32` shallow array both <64KiB. Tests: expanded `test_conservative_tree_schema_parity.py`.
- Capability strict bool parity for `available`/`supported`; root services/features max128 unchanged. Tests: capability loose-bool runtime/schema cases.
- Admin catalog `validate_safe_project_id` on `owner_project_id`/`project_access_id`. Tests: admin catalog secret project ID rejection.
- Expand secret assignment/auth schemes: `Authorization: Token`, standalone `Basic`/`Bearer`/`Token` (runtime + ECMA-262 schema). Tests: expanded `test_safe_metadata_schema_portability.py`.

**Luna pass-12 Important remediation (2026-08-01, worker round 12):**

- Bound/safe-validate `provider_created_at`/`provider_updated_at` in runtime and `inventory_batch.schema.json` (`ProviderTimestampString`, ISO-8601 pattern, maxLength 64, secret reject). Tests: timestamp contract cases.
- Enforce root `attributes` max128 at runtime (`MAX_ROOT_MAP_ENTRIES`). Test: `test_runtime_and_schema_both_reject_attributes_root_exceeding_128_entries`.
- Align `CapabilityDocument` root `services`/`features` count to schema max128 with explicit runtime checks; nested extras remain conservative max4; `schema_version` maxLength 16 parity in runtime/schema. Tests: capability count/schema_version cases.
- Attachment structural limits tightened (`MAX_ATTACHMENT_KEY_LENGTH=32`, dedicated `AttachmentDepth*` schema); deterministic worst-case schema-valid attachment <64KiB test; runtime byte check retained. Test: `test_worst_case_schema_valid_attachment_serializes_below_64_kib`.
- Remove repository `disk_format.lower()` normalization; filter uses strict lowercase value from validated ingestion/API.
- Bounded `validate_safe_project_id` / `SafeProjectIdString` for compatibility and inventory project-ID lists (nonempty max255, secret reject). Tests: `test_snapshot_rejects_*project*`.
- Expand runtime/portable schema secret-value detection for `password=`, `token=`, `authorization bearer/basic` outside URLs with adversarial false-positive tests. Tests: expanded `test_safe_metadata_schema_portability.py`.

**Luna pass-11 Important remediation (2026-08-01, worker round 11):**

- Attachment root `maxProperties` 4 runtime/schema parity via `validate_attachment_tree` `shallow_map_depth=-1`; capability `ExtraListItem` scalar-only matching runtime list rejection. Tests: `test_conservative_tree_schema_parity.py` attachment/capability cases.
- `disk_format` strict lowercase: no CPS normalization; runtime/schema/filter/projection reject uppercase; checksum test updated. Tests: `test_inventory_checksum_rejects_uppercase_disk_format`.
- Catalog API Pydantic `Field` min/max 255 (checksum 128, status 64, disk_format 32) and fail-closed projection via `validate_safe_catalog_string`. Tests: admin detail overlong/secret cases.
- Compatibility snapshots bound all strings and project lists (`max_length=256`). Tests: `test_snapshot_rejects_*`.
- Top-level `InventoryBatchItem` strings validated with `validate_safe_catalog_string` before persistence; schema uses `CatalogSafeString`/`CatalogStatusSafeString`/`CatalogChecksumSafeString`. Tests: secret-bearing top-level inventory cases.
- Contract CLI (`semantic.py`) validates complete `InventoryBatchPayload` for every `cloud.inventory.batch` fixture (legacy + catalog), not item fragments only. Tests: `test_semantic_validation_validates_all_inventory_batch_payloads_against_json_schema`.

**Luna pass-10 Important remediation (2026-08-01, worker round 10):**

- Unified conservative metadata/attachment runtime via `validate_conservative_tree`; JSON Schema `MetadataListItem` scalar-only, `BoundedMetadataMap` root 128 entries, attachment objects `$ref MetadataDepth1`; bidirectional parity tests in `tests/unit/contracts/test_conservative_tree_schema_parity.py`.
- `CatalogSafeString`/`BoundedCatalogString` maxLength 255 in schema; runtime unchanged at 255 for catalog strings.
- `validate_disk_format` allow-list shared across ingestion, JSON Schema `AllowedDiskFormat`, catalog projection, compatibility, and filter validation.
- `CatalogImageSnapshot`/`CatalogFlavorSnapshot` `strict=True` with documented numeric upper bounds; `CatalogCompatibilityRequest` `extra=forbid`.
- Member catalog list/detail map malformed legacy projection to non-enumerating `404` via `_member_*_summary` wrappers.
- Secret URL detection matches credential/signed patterns anywhere in string (runtime + schema `.*` prefix).
- Catalog numeric filters enforce contract maxima in Query annotations and `_validate_numeric_filter_bounds`.
- `semantic.py` validates catalog inventory fixtures against `inventory_batch.schema.json` and canonical capability document against `capability_document.schema.json`; regression in `test_delivery_contract.py`.

**Luna pass-9 Important remediation (2026-08-01, worker round 9):**

- Shared conservative tree (`depth 4`, nested `map/list 4`, `string 128`) for generic metadata, attachments, and capability extras; runtime retains explicit serialized 64 KiB checks; dedicated `tags`/`member_project_ids`/`access_project_ids` keep documented maxima and bypass generic list validator.
- JSON Schema patterns are ECMA-262 portable (no inline flags); compile test in `tests/unit/contracts/test_safe_metadata_schema_portability.py`.
- Secret detection covers separator-variant keys, credential userinfo URLs, and `signed_url=` query values in runtime and schema.
- `InventoryBatchItem` uses `strict=True`; admin/compatibility projections enforce exact numeric min/max and bool rejection.
- Catalog pagination caps resolved offset at `MAX_CATALOG_OFFSET = 100_000`.

**Luna pass-6 Important remediation (2026-08-01, worker round 6):**

- `InventoryBatchItem`/`_validate_catalog_attributes` enforce strict bool/int/string semantics aligned with `inventory_batch.schema.json` (`type(value) is int/bool/str`, reject bool `virtual_size_bytes`, `container_format` max 255); contract tests cover Pydantic and JSON Schema parity.
- Attachments validated as bounded `BoundedAttachmentObject` arrays (max 32 object entries, recursive `validate_metadata_tree`, serialized 64 KiB); non-object attachment entries rejected.
- `SafePropertyName`/`is_secret_key` reject `credential` and `signed_url`/`signedurl` normalized substring variants in Pydantic, capability runtime, and both JSON Schemas.
- `CapabilityDocument` runtime uses `validate_metadata_tree` (depth/map/list/per-string/serialized bounds) matching recursive capability schema; tests assert runtime rejection of deep nesting and oversized maps.
- Image ownership: `resolve_owner_project_provider_resource_id` detects conflicting sources; Image conflict updates `project_id`/`project_provider_resource_id` atomically only when incoming owner resolves (`project_id IS NOT NULL`), preserving canonical pair on absent/unresolved refresh; integration `test_image_refresh_with_unresolved_owner_preserves_project_linkage_atomically`.
- Admin catalog projections require dict `provider_attributes` (`400 VALIDATION_FAILED`); legacy bool `virtual_size_bytes` and overlong `container_format` fail closed in response projection tests.

**Luna pass-5 Important remediation (2026-08-01, worker round 5):**

- `inventory_batch.schema.json` matches Pydantic for secret-key substring variants, RSA/EC/OPENSSH PEM private keys, credential/signed/x-goog/AWS URL values, strict `catalog_approved` boolean, and bounded `tags`; contract tests assert schema-layer rejection (no Pydantic-only divergence).
- `capability_document.schema.json` recursively bounds object/array/string extra fields (depth/count/size) and rejects the same PEM/credential/x-goog patterns and secret key substrings as `safe_metadata`.
- Image upsert typed conflict branch coalesces `project_id`/`project_provider_resource_id` when refresh omits ownership; integration regression `test_image_refresh_without_ownership_preserves_project_linkage`.
- Admin catalog projection converts legacy invalid metadata (non-object maps/lists) to `400 VALIDATION_FAILED` via `InvalidRequestError`, not uncaught `500`.

**Luna pass-4 Important remediation (2026-08-01, worker round 4):**

- Member catalog rejects any supplied `owner_project_id`, `project_access_id`, and `include_deleted` (including explicit `false`); tenant-selection filters never reach the repository.
- Shared `safe_metadata.py` normalizes secret keys (camel/snake/separator variants including `userData`, `rawResponse`, `privateKey`, `caCertPem`) and rejects PEM/private/signed URL values recursively before persistence and in capability validation.
- `inventory_batch.schema.json` uses recursive bounded metadata `$defs` with `maxLength`/`maxItems`/`maxProperties`/depth and `propertyNames` negative secret patterns; contract tests require schema-layer rejection (no documented Pydantic-only divergence).
- Legacy admin projections enforce 255-character tag/member/access entries and 64-KiB serialized bounds (fail closed, no truncation).
- Image upsert conflict branch orders typed `Image`/`Flavor` refresh before generic `project_id` coalesce; integration regression covers initial then changed batch refresh of every typed catalog field.
- Capability JSON Schema extra fields use the same secret `propertyNames` and bounded string patterns as inventory metadata.

- [ ] **Step 3: Rerun affected and full automated gates**

Run focused tests for each changed area, then:

```bash
rtk ruff check src tests
rtk mypy src
rtk pytest -q
python -m cps.contracts.validate_contracts
rtk git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Require reviewer re-approval**

Send the final diff and fresh results to the same luna reviewer. Do not proceed without explicit final approval and no unresolved Critical/High defect.

### Task 7: Task-Diff Secret Scan

The Codex Security plugin workflow was removed by direct user instruction on
2026-08-01. Run the repository secret scanner over the task diff, classify all
candidates without copying sensitive values, and preserve only a redacted
summary in the runbook.

### Task 8: Verification, Live Evidence, Cleanup, and Runbook

**Files:**
- Create: `docs/runbooks/sprint-19-catalog-contracts.md`
- Modify: `plan/tasks/sprint-19/CPS-1901-catalog-contracts.md`
- Modify: `plan/sprints/sprint-19.md`

- [ ] **Step 1: Invoke verification discipline**

Invoke `superpowers:verification-before-completion`.

- [ ] **Step 2: Run fresh full quality gates**

Run:

```bash
rtk ruff check src tests
rtk mypy src
rtk pytest -q
CPS_RUN_INTEGRATION=1 rtk pytest -q -m integration
python -m cps.contracts.validate_contracts
rtk alembic heads
rtk git diff --check
detect-secrets scan --all-files
```

Expected: all commands exit 0, Alembic reports only `20260801_0017 (head)`, and the secret scan contains no new verified secret.

- [ ] **Step 3: Trigger and poll live inventory**

Use environment variables without printing token values:

```bash
export CPS_URL="${CPS_URL:?set CPS_URL}"
export CPS_ADMIN_TOKEN="${CPS_ADMIN_TOKEN:?set CPS_ADMIN_TOKEN}"
export CPS_MEMBER_TOKEN="${CPS_MEMBER_TOKEN:?set CPS_MEMBER_TOKEN}"
export CONNECTION_ID="${CONNECTION_ID:?set CONNECTION_ID}"
export PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
export IDEMPOTENCY_KEY="cps-1901-$(date +%s)"

curl -fsS -X POST \
  -H "Authorization: Bearer $CPS_ADMIN_TOKEN" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -H "Content-Type: application/json" \
  "$CPS_URL/api/v1/admin/provider-connections/$CONNECTION_ID/inventory-syncs" \
  -d '{"collections":["image","flavor"],"batch_size":100}' \
  > /tmp/cps-1901-sync.json

export OPERATION_ID="$(
  python -c 'import json; print(json.load(open("/tmp/cps-1901-sync.json"))["data"]["operation_id"])'
)"

for attempt in $(seq 1 60); do
  curl -fsS \
    -H "Authorization: Bearer $CPS_ADMIN_TOKEN" \
    "$CPS_URL/api/v1/admin/operations/$OPERATION_ID" \
    > /tmp/cps-1901-operation.json
  state="$(
    python -c 'import json; print(json.load(open("/tmp/cps-1901-operation.json"))["data"]["state"])'
  )"
  case "$state" in
    SUCCEEDED) break ;;
    FAILED|TIMED_OUT|CANCELLED) exit 1 ;;
  esac
  sleep 5
done
test "$state" = SUCCEEDED
```

Expected: terminal `SUCCEEDED`. Delete `/tmp` response files after extracting redacted evidence.

- [ ] **Step 4: Query member and admin catalog views**

Run:

```bash
curl -fsS -H "Authorization: Bearer $CPS_MEMBER_TOKEN" \
  "$CPS_URL/api/v1/provider-connections/$CONNECTION_ID/catalog?resource_type=image&limit=100" \
  > /tmp/cps-1901-member-images.json
curl -fsS -H "Authorization: Bearer $CPS_MEMBER_TOKEN" \
  "$CPS_URL/api/v1/provider-connections/$CONNECTION_ID/catalog?resource_type=flavor&limit=100" \
  > /tmp/cps-1901-member-flavors.json
curl -fsS -H "Authorization: Bearer $CPS_ADMIN_TOKEN" \
  "$CPS_URL/api/v1/admin/provider-connections/$CONNECTION_ID/catalog?resource_type=image&limit=100" \
  > /tmp/cps-1901-admin-images.json
curl -fsS -H "Authorization: Bearer $CPS_ADMIN_TOKEN" \
  "$CPS_URL/api/v1/admin/provider-connections/$CONNECTION_ID/catalog?resource_type=flavor&limit=100" \
  > /tmp/cps-1901-admin-flavors.json
```

Expected: member data contains only approved/live/scope-visible items; admin data contains bounded full fields and no `provider_attributes`, token, password, signed URL, or raw response.

- [ ] **Step 5: Independently compare OpenStack**

Run with an already configured, non-recorded `clouds.yaml`:

```bash
openstack image list --long -f json > /tmp/cps-1901-os-images.json
openstack flavor list --all -f json > /tmp/cps-1901-os-flavors.json
openstack image show "$IMAGE_PROVIDER_ID" -f json > /tmp/cps-1901-os-image.json
openstack flavor show "$FLAVOR_PROVIDER_ID" -f json > /tmp/cps-1901-os-flavor.json
```

Compare provider IDs and every mapped material field. If CPS inventory was stale, trigger the targeted refresh, poll terminal success, and compare again. Do not record token/catalog data or unsafe raw provider properties.

- [ ] **Step 6: Exercise compatibility live**

Run:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $CPS_MEMBER_TOKEN" \
  -H "Content-Type: application/json" \
  "$CPS_URL/api/v1/catalog/compatibility" \
  -d "{
    \"use\":\"LAUNCH\",
    \"provider_connection_id\":\"$CONNECTION_ID\",
    \"project_provider_resource_id\":\"$PROJECT_ID\",
    \"image_provider_resource_id\":\"$IMAGE_PROVIDER_ID\",
    \"flavor_provider_resource_id\":\"$FLAVOR_PROVIDER_ID\"
  }"
```

Expected: result matches independently checked approval, status, scope, format, RAM, and disk facts.

- [ ] **Step 7: Prove cleanup**

This story is read-only apart from inventory refresh; it creates no OpenStack resource. Record cleanup as `none required`, then prove no disposable resource was created by comparing pre/post image/flavor provider-ID sets. Remove all `/tmp/cps-1901-*.json` files after redacted extraction.

- [ ] **Step 8: Write the redacted runbook**

Create `docs/runbooks/sprint-19-catalog-contracts.md` with environment/build identifiers, exact commands, exit codes, contract/checksum hash, migration result, review approval, secret-scan disposition, correlation/operation IDs, field comparison, compatibility result, cleanup proof, and limitations. Never include bearer tokens, signed URLs, `clouds.yaml`, credentials, binary artifacts, `user_data`, raw unsafe provider bodies, or unredacted metadata.

- [ ] **Step 9: Update Sprint evidence**

Update the task and Sprint 19 evidence only after all gates pass. Keep status not-Done until both CPS-1901 and OPS-1901 live evidence and pinned checksums are complete.

### Task 9: Finish Branch and Git Authorization Gate

**Files:** Entire reviewed CPS-1901 diff only.

- [ ] **Step 1: Invoke branch-finishing workflow**

Invoke `superpowers:finishing-a-development-branch`.

- [ ] **Step 2: Verify final diff scope**

Run:

```bash
rtk git status --short
rtk git diff --check
rtk git diff --stat
```

Expected: only files listed in this plan; no secret, cache, local data, generated test artifact, or unrelated change.

- [ ] **Step 3: Stop for exact Git authorization**

Present the proposed task-scoped commits and stop. Do not run `git add`, `git commit`, `git push`, amend, rebase, merge, or tag unless the user explicitly authorizes that exact Git action in the current turn.

- [ ] **Step 4: Execute authorized commits only**

If explicitly authorized, use the prepared Task 2–5 boundaries plus one evidence commit when reviewability benefits; otherwise squash proposal to:

```text
feat(cps): add catalog detail and compatibility contracts
```

- [ ] **Step 5: Record Git evidence**

After an explicitly authorized push, record branch, commit hash(es), remote ref, and clean worktree status in the runbook and Sprint evidence. Never claim Done before OPS pin/live verification is linked.

## Plan Self-Review

- [x] Acceptance and out-of-scope boundaries are explicit.
- [x] Exact production, test, migration, evidence, and commit scope is listed.
- [x] Contract compatibility/version and CPS→OPS pin order are explicit.
- [x] Index-only migration choice is justified; no unnecessary typed column is introduced.
- [x] RED, observed failure, minimal GREEN, and refactor steps are present for each behavior slice.
- [x] Independent luna review, remediation, and re-review are mandatory.
- [x] Authorization/threat scope, independent review, and task-diff secret scanning are explicit.
- [x] Fresh focused/full verification, live curl, terminal operation polling, independent OpenStack CLI comparison, cleanup proof, and redacted runbook are exact.
- [x] Git mutation is separately authorization-gated with task-scoped commit boundaries.
- [x] No unresolved placeholder or design choice remains.
