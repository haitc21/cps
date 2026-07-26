# Provider credential, tenant ownership, and authorization design

**Status:** Approved for Sprint 13 planning  
**Date:** 2026-07-26  
**Implementation scope:** CPS and OPS only  
**External systems:** TMS is read-only from this delivery's perspective; LMS is out of scope

## 1. Decisions

1. A CMP provider is onboarded by a CMP administrator with one highest-privilege
   OpenStack account. That credential belongs to the provider aggregate.
2. Provider connections represent OpenStack scope and region only. They do not
   own or select credentials.
3. Every tenant-owned inventory resource carries both the provider's OpenStack
   project identifier and a nullable foreign key to the canonical CPS project.
4. A canonical CPS project maps one OpenStack project to one TMS organization
   and workspace.
5. Every user-initiated resource use case is authorized before CPS creates an
   operation, publishes a command, or returns tenant data.
6. CPS resolves resource ownership from persisted data. It never trusts
   `org_id` or `workspace_id` supplied by a client for an existing resource.
7. TMS remains the authorization authority. Sprint 13 implements a CPS client
   boundary and deterministic stub; it does not modify TMS or LMS.
8. OPS never calls TMS. It accepts only the authorization decision context
   attached by CPS and never makes an independent tenant-policy decision.

## 2. Provider-owned credential

The standalone `credentials` table and credential CRUD API are removed. The
following encrypted fields move to `providers`:

- `username_ciphertext`
- `username_nonce`
- `password_ciphertext`
- `password_nonce`
- `encryption_key_version`
- `user_domain_name`
- `credential_rotated_at`

AES-GCM remains mandatory. Plaintext username and password never enter public
views, operation payloads, RabbitMQ, logs, or fixtures. Encryption additional
authenticated data changes from credential identity to:

```text
{provider_id}:{key_version}:{field_label}
```

`provider_connections.credential_id` is removed. Credential resolution accepts
only `provider_connection_id`, resolves its provider, and decrypts that
provider's secret. Rotating a provider credential returns every connection for
that provider to `PENDING_VALIDATION`.

Because the development database is currently empty, Sprint 13 uses a hard
schema cut. The migration must still detect and reject ambiguous legacy data
where one provider references more than one distinct credential.

## 3. Canonical tenant ownership

The `projects` table becomes the canonical OpenStack-project-to-TMS mapping:

```text
id                              UUID primary key
provider_id                     UUID not null -> providers.id
provider_connection_id          UUID not null -> provider_connections.id
provider_resource_id            VARCHAR(255) OpenStack project ID
org_id                          VARCHAR(255) nullable TMS Organization._id
workspace_id                    VARCHAR(255) nullable TMS Workspace._id
ownership_state                 MANAGED | UNBOUND | DISABLED
```

Required constraints:

```text
unique(provider_id, provider_resource_id)
unique(provider_id, org_id, workspace_id) where workspace_id is not null
```

MongoDB identifiers cross service boundaries as opaque strings. Production code
does not manufacture TMS identifiers. Tests use deterministic valid ObjectId
strings:

```text
org_id       = 64b000000000000000000001
workspace_id = 64b000000000000000000101
```

`identity_bindings` remains the workflow/status record. A project binding that
reaches `READY` populates the canonical project ownership columns. Inventory
refresh may update provider attributes but must not erase CMP ownership.

## 4. Resource project linkage

Tenant-owned resource tables add:

```text
project_id                       UUID nullable -> projects.id ON DELETE RESTRICT
project_provider_resource_id     VARCHAR(255) nullable
```

This applies to instances, volumes, networks, subnets, ports, routers, security
groups, security-group rules, floating IPs, images, quotas, and future snapshots.
Regions, identity domains, and flavors are provider-global and do not receive
these fields.

Inventory normalizes owner identity in this order:

1. `location.project.id`
2. `project_id`
3. `tenant_id`
4. project-scoped connection only as an explicit fallback

The repository resolves `(provider_id, project_provider_resource_id)` to the
canonical `projects.id`. A resource with unresolved ownership remains visible
only to CMP administrators and cannot be mutated by a workspace user.

## 5. Authorization boundary

CPS defines an outbound port:

```python
authorize(
    *,
    bearer_token: str,
    org_id: str,
    workspace_id: str,
    permission: str,
    resource_type: str,
    resource_id: str,
    correlation_id: UUID,
) -> AuthorizationDecision
```

The future TMS integration target is:

```text
POST /internal/v1/authorization/check
Authorization: Bearer <original user JWT>
X-Service-Name: cps
X-Correlation-ID: <correlation ID>
```

Sprint 13 does not add this endpoint to TMS. CPS provides:

- a production HTTP adapter behind configuration, disabled until an endpoint is
  supplied;
- a deterministic stub adapter for unit, integration, and local acceptance;
- strict timeout, response validation, redaction, and fail-closed behavior.

The subject is derived by TMS from the original bearer token; CPS never sends a
client-selected user ID as authorization authority.

Permission names are centralized in CPS contracts:

| Resource family | Read | Write | Delete |
|---|---|---|---|
| Compute | `ws:compute:read` | `ws:compute:write` | `ws:compute:delete` |
| Storage | `ws:storage:read` | `ws:storage:write` | `ws:storage:delete` |
| Network | `ws:network:read` | `ws:network:write` | `ws:network:delete` |
| Image | `ws:image:read` | `ws:image:write` | `ws:image:delete` |
| Project/quota | `ws:project:read` | `ws:project:write` | `ws:project:delete` |

Provider and identity-domain administration require CMP administrative
permissions and do not accept workspace ownership supplied by the caller.

## 6. Request and operation behavior

For an existing resource:

```text
request
  -> load resource and canonical project in one indexed query
  -> derive org/workspace
  -> call authorization port once for the user use case
  -> persist decision in operation.actor_context
  -> enqueue provider command
```

One business action receives one authorization decision. Internal steps such as
creating a port and attaching it to a VM do not each call TMS. A queued command
whose decision has expired before dispatch must be reauthorized or fail closed.
OPS receives no bearer token and no membership data.

List requests authorize once for the requested workspace and then filter by
`project_id`. Bulk requests group resources by workspace and authorize once per
workspace; any denied workspace rejects the atomic request.

Authorization decision audit data is limited to:

- decision ID
- subject ID returned by the authority
- organization and workspace IDs
- permission
- authorized and expiry timestamps

Tokens and role lists are never persisted.

## 7. Failure policy

- Missing project mapping: deny workspace access.
- Disabled/unbound project: deny workspace mutation.
- Invalid TMS response: `503`, no operation.
- TMS timeout/unavailable: `503`, fail closed.
- Explicit deny: `403`, no operation.
- Resource outside requested workspace: `404` or stable access-denied response,
  without disclosing cross-tenant existence.
- Cache failure never becomes allow. Any role cache belongs to TMS, not CPS.

## 8. Scope boundaries

Allowed repositories for implementation:

- `cps`
- `ops`
- `bms` only if a later billing/read-model story explicitly requires it

Sprint 13 does not modify:

- `tms`
- `lms`
- any other CMP module

The missing TMS authorization endpoint is an external dependency. Local and CI
acceptance use the CPS stub and must not hide the production fail-closed
configuration.

## 9. Acceptance gates

- Clean and upgrade migration paths pass.
- Provider onboarding persists exactly one encrypted credential aggregate.
- No credential CRUD endpoint or credential reference remains in the public or
  CPS/OPS command contract.
- Every tenant resource mutation resolves a canonical project and obtains an
  authorization decision before operation creation.
- Tenant list/get paths cannot return a resource from another workspace.
- Inventory preserves project ownership across full and targeted refresh.
- Deny, timeout, malformed response, expired decision, unbound project, and
  cross-workspace tests pass.
- Contract fixtures and checksums match in CPS and OPS.
- No test or source change is made in TMS or LMS.
