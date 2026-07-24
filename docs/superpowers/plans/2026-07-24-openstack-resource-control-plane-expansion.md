# OpenStack Resource Control Plane Expansion — Implementation Plan

**Status:** Proposed  
**Date:** 2026-07-24  
**Canonical design:** `../specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`  
**Repositories:** CPS and OPS

## Objective

Deliver standalone OpenStack resource lifecycle management through CPS/OPS
without integrating TMS, BMS, Keycloak/IAM, or LMS. Preserve CPS as the
provider-neutral durable control plane and OPS as a stateless OpenStackSDK
adapter.

## Non-goals

- No organization/workspace workflow.
- No product/SKU/pricing workflow.
- No user authentication or authorization implementation.
- No default network bundle or composite tenant bootstrap.
- No direct OpenStack service clients in CPS.
- No OPS database or durable secret storage.

## Planning rules

- The design delta must be approved before implementation.
- CPS contracts merge first; OPS pins the exact checksum in the same sprint.
- Every provider mutation begins with a failing contract/unit test.
- Each story delivers one vertical, replay-safe operation or one coherent
  persistence foundation.
- Unknown major contracts fail to DLQ; approved additive fields remain
  compatible.
- Existing dirty worktree changes are preserved and are not a dependency of
  this plan unless explicitly listed.
- Real-cloud tests use disposable resources with verified cleanup.

## Target architecture

```text
Client
  │ REST: provider-neutral resource request
  ▼
CPS API
  ├─ validate common shape, connection scope, references
  ├─ create durable operation + outbox
  └─ persist normalized inventory/result
       │ RabbitMQ command/event
       ▼
OPS worker
  ├─ resolve credential just in time
  ├─ validate capability, token scope, provider ownership
  ├─ execute supported OpenStackSDK proxy operation
  ├─ bounded waiter and replay precondition
  └─ publish normalized progress/result/error
       │
       ▼
Keystone / Nova / Neutron / Cinder / Glance
```

## Workstream A — contract and operation framework

### Task A1 — Define generic resource-operation semantics

**CPS files:**

- `src/cps/contracts/messages/`
- `src/cps/contracts/jsonschema/`
- `src/cps/contracts/fixtures/`
- `src/cps/contracts/checksums.json`
- `tests/contract/`

Deliver:

- resource reference and owner-scope models;
- create/update/delete/ensure/remove result envelope;
- normalized resource snapshot and tombstone;
- required connection scope;
- safe partial-result representation for relationship operations;
- semantic validators for operation type and payload;
- success, failure, replay, already-absent, and unsupported fixtures.

Acceptance:

- fixtures validate from both Pydantic and JSON Schema;
- payload cannot contain credential material or SDK objects;
- unknown major version is rejected;
- checksum manifest is deterministic;
- existing VM fixtures remain compatible.

### Task A2 — Generalize CPS operation creation

**CPS files:**

- `src/cps/application/operations.py`
- `src/cps/domain/operations/`
- `src/cps/api/routers/operations.py`
- `src/cps/api/schemas/`
- `tests/unit/`
- `tests/integration/`

Deliver:

- one internal resource-operation creation service using allow-listed operation
  descriptors;
- resource-specific routers call the shared service rather than accepting an
  arbitrary client-provided message type;
- common idempotency fingerprinting;
- reference ownership and scope validation ports;
- operation query filters for resource type and target ID.

Acceptance:

- arbitrary routing keys cannot be injected through REST;
- identical request/key returns the original operation;
- changed payload with reused key returns 409;
- operation and outbox commit atomically;
- actor context remains optional and secret-safe.

### Task A3 — Generalize OPS handler registration

**OPS files:**

- `src/ops/application/handlers/`
- `src/ops/messaging/consumer.py`
- `src/ops/contracts/messages/`
- `tests/unit/application/`
- `tests/unit/messaging/`

Deliver:

- typed handler registry per supported operation;
- shared handler lifecycle: resolve, connect, precondition, mutate, wait,
  normalize, publish;
- service-specific concurrency keys;
- deterministic retry and replay hooks.

Acceptance:

- validation completes before provider mutation;
- terminal publish confirm precedes command acknowledgement;
- poison contracts terminate in DLQ;
- transient failure retries remain bounded;
- shutdown safely finishes or nacks in-flight mutations.

## Workstream B — scoped provider connections

### Task B1 — CPS schema and migration

Add:

- `scope_kind` with `SYSTEM`, `DOMAIN`, `PROJECT`;
- optional domain/project provider IDs;
- validated scope metadata and timestamp;
- uniqueness/index rules per provider/region/scope.

Migration rules:

- existing rows become `PROJECT`;
- existing project name/domain fields are preserved;
- downgrade restores the previous columns without discarding credentials;
- migration refuses ambiguous invalid rows instead of guessing.

Acceptance:

- clean PostgreSQL 18 upgrade/downgrade passes;
- upgrade from current head passes with representative data;
- API responses never expose credential values;
- successful validation is required before administrative operations.

### Task B2 — OPS scope discovery and validation

Use OpenStackSDK identity/auth APIs to report:

- effective token scope;
- system/domain/project IDs where safely available;
- administrative operation capabilities;
- explicit unsupported reason when cloud policy denies scope.

Acceptance:

- OPS does not infer admin authority from username;
- raw token/catalog is never returned;
- project-scoped credentials cannot execute domain creation;
- scope discovery is compatible with clouds that do not support system scope.

## Workstream C — identity control

### Task C1 — Domain inventory

Add typed domain contract/model, full collection, targeted refresh, list/get
API, reconciliation, and tombstones.

Acceptance:

- provider identity is ID-based;
- parent/domain metadata remains bounded;
- partial identity failure cannot delete inventory;
- multiple connections do not create duplicate canonical domains.

### Task C2 — Domain lifecycle

Operations:

- create;
- update name/description/enabled;
- disable;
- delete.

Safety:

- create replay uses operation marker when supported or deterministic lookup
  using operation metadata plus provider-side state;
- delete requires disabled/empty preconditions unless `force` is explicitly
  supported in a future story;
- already absent is success/tombstone;
- domain with projects returns conflict.

### Task C3 — Project lifecycle

Operations:

- create under domain;
- update name/description/enabled;
- disable;
- delete.

Acceptance:

- domain ownership is validated twice, in CPS and OPS;
- duplicate delivery cannot create two projects;
- delete refuses active dependencies;
- completion persists normalized project inventory atomically.

### Task C4 — Roles and assignments

Add role inventory and ensure/revoke operations for user/group assignments at
system/domain/project scope.

Acceptance:

- assignment identity includes role, principal, scope, and inherited flag;
- ensure is replay-safe;
- revoke of absent assignment is idempotent;
- no user credential or token is inventoried.

### Task C5 — Quotas

Add typed quota read/update for compute, network, and block storage.

Acceptance:

- `-1`/unlimited semantics normalize explicitly;
- service absence is `SKIPPED_UNSUPPORTED`;
- update validates nonnegative/unlimited values and provider limits;
- partial service update reports per-service outcome and does not claim total
  success;
- replay reads current quota before writing.

## Workstream D — network control

### Task D1 — Inventory expansion

Add router, router interface, security group, security-group rule, and floating
IP typed inventory. Extend network/subnet/port ownership fields.

### Task D2 — Network and subnet lifecycle

Support create/update/delete with CIDR, IP version, DHCP, gateway, DNS,
allocation pool, shared/external flags gated by connection scope and capability.

### Task D3 — Router and interface lifecycle

Support router CRUD, external gateway, static routes, and idempotent
ensure/remove interface operations.

### Task D4 — Port and security lifecycle

Support port CRUD, fixed IP, security-group assignment, security-group CRUD,
and rule create/delete.

### Task D5 — Floating IP lifecycle

Support allocate, associate, disassociate, and release with project, external
network, port, and fixed-IP validation.

Network acceptance:

- CIDRs and allocation pools receive strict bounded validation;
- external/shared operations require administrative scope;
- project resources cannot reference another project's private resource;
- relationship replay checks both resources;
- delete dependency conflicts remain explicit;
- refresh returns network topology snapshots after mutation.

## Workstream E — storage and catalog control

### Task E1 — Volume type and snapshot inventory

Add typed volume-type and volume-snapshot inventory, relationships, list/get,
full reconciliation, and targeted refresh.

### Task E2 — Volume lifecycle

Support create, update metadata/name, extend, attach, detach, and delete.

Acceptance:

- size can only increase;
- attach/detach checks instance and volume state;
- multiattach is capability-gated;
- delete refuses attached volumes by default;
- VM root-volume policy remains delegated to Nova and is not double-deleted.

### Task E3 — Snapshot lifecycle

Support create, update, and delete with bounded waiter and replay behavior.

### Task E4 — Image control

Split metadata lifecycle from binary transfer:

- create/import from an approved provider-accessible source;
- update metadata/visibility;
- grant/revoke member access;
- delete.

Do not put image bytes or signed source credentials on RabbitMQ. Streaming
upload requires a separately approved data-plane design.

### Task E5 — Flavor and availability-zone control

- add typed availability-zone inventory;
- enrich flavor extra specs and project access;
- support flavor create/delete/access operations with administrative scope;
- treat flavor update as capability/provider-policy dependent.

## Workstream F — acceptance and operations

### Task F1 — Cross-resource reconciliation

Verify operation results and subsequent full sync converge for:

- domain → project;
- network → subnet → router/interface → port → floating IP;
- volume → snapshot and volume → instance attachment;
- image/flavor access bindings.

### Task F2 — Failure and recovery matrix

For every mutation class test:

- duplicate command;
- publish failure then redelivery;
- provider timeout before and after mutation;
- provider 401/403/404/409/429/5xx;
- CPS worker restart;
- OPS worker restart;
- direct provider drift;
- partial relationship mutation;
- cleanup after failed real-cloud acceptance.

### Task F3 — Observability and runbooks

Add:

- per-resource operation metrics;
- provider service latency/error counters;
- scope/capability rejection counters;
- safe DLQ replay procedure;
- disposable resource cleanup runbook;
- migration and rollback runbook.

## Sprint forecast

### Sprint 7 — scoped connection and identity foundation

Stories:

- CPS-701 canonical resource-operation contracts;
- CPS-702 scoped provider-connection migration/API;
- CPS-703 domain/project inventory persistence and query;
- OPS-701 pin resource-operation contracts;
- OPS-702 scope discovery;
- OPS-703 domain/project collectors.

Exit: an administrative connection validates its effective scope and CPS
convergently inventories domains/projects. No provider mutation is enabled
until the contract, migration, and replay design pass review.

### Sprint 8 — identity lifecycle, roles, and quotas

Stories:

- CPS-801 domain/project lifecycle API and operation handling;
- CPS-802 role and assignment inventory/API;
- CPS-803 quota inventory/API;
- OPS-801 domain/project handlers;
- OPS-802 role assignment handlers;
- OPS-803 quota collectors/handlers;
- CPS-804/OPS-804 identity real-cloud acceptance.

Exit: create/update/disable/delete disposable domains/projects, manage role
assignments, and update quotas with replay-safe terminal evidence.

### Sprint 9 — network control

Stories:

- CPS-901 network resource schemas/migrations;
- CPS-902 network/subnet operations;
- CPS-903 router/interface operations;
- CPS-904 port/security operations;
- CPS-905 floating-IP operations;
- paired OPS-901..905 collectors and handlers;
- CPS-906/OPS-906 network topology acceptance.

Exit: construct and remove a complete disposable project network topology,
including external connectivity, without manual OpenStack mutation.

### Sprint 10 — storage, image, and compute catalog

Stories:

- CPS/OPS-1001 volume type and snapshot inventory;
- CPS/OPS-1002 volume lifecycle and attachment;
- CPS/OPS-1003 snapshot lifecycle;
- CPS/OPS-1004 image metadata/import/access lifecycle;
- CPS/OPS-1005 availability zones and flavor lifecycle/access;
- CPS/OPS-1006 catalog/storage acceptance.

Exit: standalone storage and provider catalog resources are manageable through
CPS/OPS with explicit data-plane limitations.

### Sprint 11 — recovery and release

Stories:

- CPS/OPS-1101 cross-resource drift convergence;
- CPS/OPS-1102 restart/redelivery/partial-success suite;
- CPS-1103 migration/rollback and operational controls;
- OPS-1103 compatibility matrix;
- CPS/OPS-1104 real-cloud release acceptance.

Exit: the expanded provider control plane passes recovery, upgrade, cleanup,
and compatibility gates.

## Sprint 7 delivery order

1. Approve design delta and disposable administrative test policy.
2. Write CPS failing contract tests and fixtures for scope/domain/project.
3. Implement CPS canonical schemas and checksum manifest.
4. Pin exact CPS artifacts in OPS and add validation tests.
5. Write migration tests for existing project-scoped connections.
6. Implement scoped connection persistence and validation response.
7. Add domain typed persistence and extend project ownership identity.
8. Add OPS scope discovery and domain/project collectors.
9. Add CPS ingestion/query and cross-connection deduplication tests.
10. Run mocked cross-service integration.
11. Run read-only real-cloud administrative inventory acceptance.
12. Record evidence; do not start identity mutations until Sprint 8 planning.

## Definition of Done

- Approved design and selected sprint stories agree.
- CPS owns executable canonical contracts and OPS pin matches byte-for-byte.
- Every change has red-green-refactor evidence.
- Alembic clean install, current-head upgrade, and downgrade pass.
- Unit, contract, integration, format, lint, typing, secret scan, and build pass.
- RabbitMQ duplicate/redelivery and terminal publish/ack ordering pass.
- No SDK object or secret crosses OPS boundaries.
- No OpenStackSDK dependency is added to CPS.
- No persistence dependency is added to OPS.
- Real-cloud tests record provider/service versions, resource IDs needed for
  cleanup, cleanup result, and non-secret limitations.
- Sprint evidence is updated before any story is marked Done.

## Risks

| Risk | Mitigation | Owner |
|---|---|---|
| Existing connection model assumes project scope | Explicit migration to `PROJECT`; add scope before identity mutation | CPS |
| Same global resource appears through many connections | Canonical provider-level identity plus tested visibility bindings | CPS |
| OpenStack policy differs by deployment | Capability and scope discovery; never infer from username | OPS |
| Create APIs lack universal idempotency token | Operation marker where supported plus provider-state precondition; document exceptions | OPS |
| Cascading dependency deletion causes data loss | No implicit cascade; explicit conflict and future composite workflows | CPS/OPS |
| Image transfer leaks data/secrets | Metadata/import only; separate data-plane design for upload | CPS/OPS |
| Administrative acceptance damages shared cloud | Disposable prefix, dedicated domain, quotas, deny production endpoints, verified cleanup | Team |
| Scope becomes too large for one release | Vertical sprint slices with independent exit gates | Product/Team |

## Review evidence template

- Design approval:
- Selected sprint and capacity:
- CPS contract checksum:
- OPS pinned checksum:
- Migration commands/results:
- Focused test commands/results:
- Full quality gates:
- Mocked integration:
- Real-cloud environment/capabilities:
- Disposable resources and cleanup:
- Known limitations:

