# OpenStack CMP Org/Workspace Binding Specification

**Status:** Proposed for approval  
**Date:** 2026-07-24  
**Services:** CPS, OPS  
**Scope:** OpenStack only for this delivery, with schema room for VMware later

## 1. Purpose

This specification defines the minimum CPS/OPS behavior required for CMP to
create OpenStack tenant-scoped provider resources in the correct order:

1. CMP creates an `Organization`.
2. CMP creates a `Workspace` under that `Organization`.
3. CMP asks CPS to create the OpenStack `domain` for the `Organization`.
4. CMP asks CPS to create the OpenStack `project` for the `Workspace`.
5. Only after the ownership bindings exist does CMP create workload resources
   for the user.

The important rule is that CPS must not infer OpenStack `domain` or `project`
ownership from inventory that already exists on the provider. Creation is an
explicit command, not a discovery side effect.

This delivery does not integrate with TMS yet. The CPS API therefore accepts
opaque `org_id` and `workspace_id` values directly and stores them as the
binding owner references. When TMS is connected later, it will supply and
validate those IDs externally.

The public onboarding surface is a single `provider` endpoint. CMP admin
supplies the provider type, endpoint, and the highest-privilege provider
account in one request. The user does not choose provider scope in the API;
the onboarding flow assumes the account is already privileged enough to create
identity and control-plane objects.

To keep the database and contract simple, there is no separate public
`credential` object and no separate public `provider connection` object in this
model. The provider aggregate owns the encrypted admin secret, validation
state, and provider-specific connection metadata internally.

## 2. Problem statement

The current OpenStack flow is not sufficient for CMP because it treats
provider inventory as the source of truth for tenancy objects. That is the
wrong boundary.

For CMP:

- TMS owns organization and workspace lifecycle.
- CPS owns provider-side bindings and provider-side control-plane objects.
- OPS executes OpenStack mutations only.
- Inventory refresh may observe what exists on the provider, but it must not
  decide what the CMP owns.

The initial OpenStack delivery must therefore expose direct creation APIs for
`domain` and `project`.

## 3. Non-goals

This specification does not include:

- TMS integration or event wiring.
- CMP authorization checks against TMS.
- BMS, billing, product, or pricing.
- Keycloak/IAM integration.
- VMware implementation.
- Automatic import of existing provider resources as ownership bindings.
- Full lifecycle management for domain/project beyond what is required for
  creation, lookup, and safe duplicate handling.

## 4. Hard invariants

The implementation must obey all of the following:

- `Organization` maps to one OpenStack `domain`.
- `Workspace` maps to one OpenStack `project`.
- CPS must store `org_id` on every domain binding row.
- CPS must store `org_id` and `workspace_id` on every project binding row.
- A project binding cannot exist without a domain binding for the same
  `org_id`.
- Creation is explicit. CPS must not create a domain or project just because
  inventory refresh sees an unbound object on the provider.
- CPS must never auto-attach an unbound provider `domain` or `project` to a
  CMP owner based on matching name alone.
- If a provider-side name collision exists without an explicit binding, the
  operation must fail with a conflict rather than silently reusing the object.
- The OpenStack implementation must be first-class, but the data model must
  remain extensible enough that VMware can later introduce different binding
  kinds without replacing the schema.

## 5. Ownership and binding model

The implementation should treat ownership as a binding record, not as a side
effect of inventory.

Recommended canonical fields for a binding record:

- `id`
- `provider_id`
- `provider_connection_id`
- `provider_type`
- `binding_kind`
- `org_id`
- `workspace_id` where applicable
- `provider_resource_id`
- `provider_resource_name`
- `status`
- `last_error_code`
- `last_error_message`
- `created_at`
- `updated_at`
- `version`

Binding kinds for this delivery:

- `OPENSTACK_DOMAIN`
- `OPENSTACK_PROJECT`

Field rules:

- `org_id` is required for both binding kinds.
- `workspace_id` is required only for `OPENSTACK_PROJECT`.
- `provider_resource_id` is the provider-side OpenStack ID.
- `provider_resource_name` is the OpenStack display name and is not an owner
  identity.
- `status` is a CPS-managed state such as `PENDING`, `READY`, `FAILED`, or
  `DELETED`.
- The binding record is the source of truth for CMP ownership, not the
  OpenStack inventory row.

If the implementation keeps separate tables for domain and project, those
tables must still contain the same owner reference columns and the same
uniqueness rules.

## 6. Uniqueness rules

The database must enforce the following natural keys:

- one OpenStack domain binding per `(provider_connection_id, org_id)`
- one OpenStack project binding per
  `(provider_connection_id, org_id, workspace_id)`

Additional safety constraints:

- `provider_resource_id` must be unique within a provider connection and
  binding kind.
- The project table must reference a domain binding row or at minimum persist
  the owning domain provider ID so the relationship can be reconstructed
  without name matching.
- A create request with the same natural key must be idempotent.
- A conflicting existing row with a different provider resource ID must fail
  closed.

## 7. API contract

All routes live under `/api/v1`.

### 7.1 Create domain

`POST /api/v1/provider-connections/{provider_connection_id}/identity-domains`

Request:

```json
{
  "org_id": "org-uuid",
  "name": "org-acme",
  "description": "optional human-readable description"
}
```

Rules:

- The connected provider must be `OPENSTACK`.
- The provider connection must have system-level capability for identity
  mutation.
- `org_id` is required and immutable after create.
- The request is idempotent on `(provider_connection_id, org_id)`.
- If an existing binding already matches the same natural key and provider
  resource, return the existing binding.
- If a binding exists with the same natural key but a different provider
  resource, fail with conflict.

Response:

```json
{
  "id": "binding-uuid",
  "provider_connection_id": "provider-connection-uuid",
  "provider_type": "OPENSTACK",
  "binding_kind": "OPENSTACK_DOMAIN",
  "org_id": "org-uuid",
  "workspace_id": null,
  "provider_resource_id": "openstack-domain-id",
  "provider_resource_name": "org-acme",
  "status": "READY",
  "created_at": "2026-07-24T00:00:00Z",
  "updated_at": "2026-07-24T00:00:00Z",
  "version": 1
}
```

### 7.2 Create project

`POST /api/v1/provider-connections/{provider_connection_id}/identity-projects`

Request:

```json
{
  "org_id": "org-uuid",
  "workspace_id": "workspace-uuid",
  "name": "ws-payments",
  "description": "optional human-readable description"
}
```

Rules:

- The connected provider must be `OPENSTACK`.
- The provider connection must have system-level capability for identity
  mutation.
- The matching domain binding for the same `org_id` must already exist.
- `org_id` and `workspace_id` are both required and immutable after create.
- The request is idempotent on
  `(provider_connection_id, org_id, workspace_id)`.
- If the domain binding is missing, fail with a dependency error.
- If an existing binding already matches the same natural key and provider
  resource, return the existing binding.
- If a binding exists with the same natural key but a different provider
  resource, fail with conflict.

Response:

```json
{
  "id": "binding-uuid",
  "provider_connection_id": "provider-connection-uuid",
  "provider_type": "OPENSTACK",
  "binding_kind": "OPENSTACK_PROJECT",
  "org_id": "org-uuid",
  "workspace_id": "workspace-uuid",
  "provider_resource_id": "openstack-project-id",
  "provider_resource_name": "ws-payments",
  "status": "READY",
  "created_at": "2026-07-24T00:00:00Z",
  "updated_at": "2026-07-24T00:00:00Z",
  "version": 1
}
```

### 7.3 Lookup and list

The implementation must expose lookup endpoints that allow CMP and later TMS
to retrieve bindings by owner IDs without relying on provider inventory names.

Required filters:

- `provider_connection_id`
- `provider_type`
- `binding_kind`
- `org_id`
- `workspace_id`
- `provider_resource_id`
- `status`

Recommended public endpoints:

- `GET /api/v1/identity-domains?org_id=...`
- `GET /api/v1/identity-projects?org_id=...&workspace_id=...`
- `GET /api/v1/identity-domains/{id}`
- `GET /api/v1/identity-projects/{id}`

The list API must never infer ownership from inventory search by name. Name is
only a display field.

## 8. Control-plane workflow

The expected control flow is:

1. CMP obtains or already knows `org_id` and `workspace_id`.
2. CMP checks whether an OpenStack domain binding already exists for the
   organization.
3. If not, CMP calls the CPS create-domain API.
4. CPS commands OPS to create the OpenStack domain.
5. CPS persists the binding row with `org_id`.
6. CMP checks whether an OpenStack project binding already exists for the
   workspace.
7. If not, CMP calls the CPS create-project API.
8. CPS commands OPS to create the OpenStack project under the owning domain.
9. CPS persists the binding row with `org_id` and `workspace_id`.
10. CMP uses the resulting bindings when creating workload resources.

This flow is intentional:

- domain/project creation is an explicit action;
- inventory refresh is a verification mechanism, not an allocator;
- ownership is stored in CPS, not derived from OpenStack inventory.

## 9. OPS behavior

OPS must implement OpenStack identity mutations for:

- domain create
- project create

OPS requirements:

- use the resolved provider connection and credential only for the active
  request;
- validate that the connection scope is sufficient before mutation;
- return the provider-side resource ID and name on success;
- normalize errors into safe CPS-facing error codes;
- not persist provider state locally;
- not treat a discovered provider object as already owned by CMP unless CPS
  explicitly supplied the natural key for that create request.

If the provider already has an object with the requested name but CPS does not
have a binding row for the requested owner key, OPS must not silently adopt
that object as the new binding. It must return a conflict or explicit already-
exists outcome that CPS can map to the correct safe response.

## 10. Inventory rules

Inventory is allowed to observe domains and projects, but the collector must
remain strictly read-only with respect to ownership.

Collector behavior:

- record provider-side existence, name, status, timestamps, and IDs;
- preserve the owner binding columns if a matching CPS binding already exists;
- do not create a binding just because a provider object exists;
- do not update `org_id` or `workspace_id` from provider discovery;
- never overwrite a binding owner key from inventory data;
- mark unbound provider objects as discovered-only unless an explicit create
  or import flow exists.

This rule is the main guardrail against the earlier incorrect flow.

## 11. Error handling

The implementation must use explicit, stable errors. Recommended errors:

- `PROVIDER_NOT_OPENSTACK`
- `PROVIDER_CONNECTION_SCOPE_INSUFFICIENT`
- `DOMAIN_BINDING_NOT_FOUND`
- `PROJECT_DEPENDS_ON_DOMAIN`
- `DOMAIN_ALREADY_BOUND`
- `PROJECT_ALREADY_BOUND`
- `PROVIDER_OBJECT_CONFLICT`
- `PROVIDER_OBJECT_ALREADY_EXISTS`
- `OWNER_SCOPE_INVALID`
- `MESSAGE_SCHEMA_UNSUPPORTED`

Error semantics:

- missing owner IDs fail validation before any provider call;
- domain creation without system scope fails before mutation;
- project creation without a domain binding fails before mutation;
- duplicate create with the same natural key is idempotent when the existing
  provider resource matches;
- name-only collisions are conflicts, not implicit adoption.

## 12. Future-proofing for VMware

This delivery only implements OpenStack behavior, but the schema must not be
hard-coded as "domain table" and "project table" in a way that blocks later
provider types.

Minimum future-proofing rule:

- keep the ownership-binding concept generic enough that VMware can add its
  own binding kinds later;
- do not make OpenStack inventory assumptions part of the core binding
  identity;
- keep `provider_type` and `binding_kind` explicit in the stored model.

The immediate implementation still uses OpenStack-specific creation APIs and
OpenStack-specific validation.

## 13. Acceptance criteria

The spec is considered satisfied when all of the following are true:

- CPS exposes a create-domain API that requires `org_id`.
- CPS exposes a create-project API that requires `org_id` and
  `workspace_id`.
- CPS stores `org_id` on domain binding rows.
- CPS stores `org_id` and `workspace_id` on project binding rows.
- Project creation fails if the matching domain binding does not exist.
- Repeated create requests for the same natural key are idempotent.
- Discovery/inventory cannot auto-create or auto-adopt bindings.
- A provider-side object with a matching name but no binding does not get
  silently reused.
- The implementation remains explicit about `OPENSTACK` as the first provider
  type, while keeping the binding model extensible for future VMware support.
