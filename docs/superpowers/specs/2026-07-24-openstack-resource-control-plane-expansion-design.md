# OpenStack Resource Control Plane Expansion Design

**Status:** Proposed for approval  
**Date:** 2026-07-24  
**Services:** Cloud Provider Management Service (CPS), OpenStack Provider Service (OPS)  
**Extends:** `2026-07-16-openstack-cloud-provider-management-design.md`

## 1. Purpose

Expand CPS/OPS from provider inventory plus VM lifecycle into a provider-neutral
resource control plane capable of administering OpenStack identity, network,
storage, image, and compute-catalog resources.

This design deliberately excludes TMS, BMS, Keycloak/IAM, LMS, VMware, and
end-user product orchestration. The public APIs retain optional actor,
organization, and workspace context fields, but this delivery does not enforce
tenant authorization or call those services.

The existing architectural boundary remains:

- CPS owns public APIs, canonical contracts, durable operations, normalized
  inventory, desired-state references, and PostgreSQL truth.
- OPS is a stateless OpenStack adapter using supported OpenStackSDK APIs.
- RabbitMQ carries mutation commands and provider results.
- Credentials remain referenced in messages and resolved just in time.

## 2. Problem statement

The approved first delivery intentionally excludes tenant orchestration and
standalone CRUD for networks, subnets, ports, security groups, key pairs,
images, flavors, and volumes. That scope is sufficient for creating a VM from
pre-existing resources but not for operating a Cloud Management Platform.

CPS currently inventories project, flavor, image, network, subnet, port, and
volume resources. Its mutation API is limited to connection validation,
inventory collection/refresh, and instance lifecycle. OPS has matching
collectors and handlers only for those paths.

The expanded control plane must:

1. discover and expose sellable/configurable provider resources;
2. create and manage standalone provider resources before VM provisioning;
3. preserve provider-neutral CPS contracts;
4. remain replay-safe under at-least-once delivery;
5. support administrative identity operations without weakening project-scoped
   workload isolation.

## 3. Scope

### 3.1 Included

Identity:

- domain inventory and lifecycle;
- project lifecycle under a domain;
- project quota read/update for compute, network, and block storage;
- role inventory and role assignment lifecycle;
- administrative and project-scoped provider connections.

Compute catalog:

- availability-zone inventory;
- flavor detail and extra-spec inventory;
- flavor lifecycle and project access where provider capability permits.

Image:

- image inventory improvements;
- image create/import/upload metadata workflow;
- image update, visibility/member access, and delete.

Network:

- network, subnet, router, router-interface, port, security-group,
  security-group-rule, and floating-IP inventory;
- standalone lifecycle operations for those resources;
- explicit external-network and project ownership validation.

Block storage:

- volume-type, volume, and snapshot inventory;
- standalone volume and snapshot lifecycle;
- attach, detach, extend, and delete;
- volume-type lifecycle as an administrative operation where supported.

Cross-cutting:

- typed capability flags per operation;
- normalized result snapshots and tombstones;
- operation idempotency and provider-side replay checks;
- full and targeted inventory reconciliation;
- migration and upgrade safety for existing CPS deployments.

### 3.2 Excluded

- TMS organization/workspace integration;
- BMS product, SKU, price, subscription, usage, or billing integration;
- Keycloak authentication/authorization and service identity;
- LMS audit publishing;
- automatic creation of a default resource bundle;
- Heat-based composite orchestration;
- load balancer, VPN, DNS, database, Kubernetes, object storage, and file-share
  product operations;
- OpenStack notification-bus ingestion;
- VMware behavior.

## 4. Provider connection scope

The current invariant that one connection represents exactly one OpenStack
project and region cannot support creation of domains or projects. Replace it
with an explicit scope model:

| Scope kind | OpenStack scope | Permitted use |
|---|---|---|
| `SYSTEM` | system/admin or cloud-admin credential | domains, projects, roles, quotas, public flavors, shared/external infrastructure |
| `DOMAIN` | one domain | projects and domain-contained role assignments |
| `PROJECT` | one project | workload, network, port, security, floating IP, volume, snapshot, image access |

Rules:

- Existing provider connections migrate to `PROJECT`.
- Every connection remains bound to exactly one provider and region.
- Scope identifiers are explicit and immutable after successful validation.
- A command declares its required scope kind.
- CPS rejects a command when the selected connection cannot satisfy the common
  scope rule.
- OPS revalidates token scope and provider ownership immediately before
  mutation.
- CPS never infers administrative authority solely from a role or connection
  name.
- Credential material and tokens remain secret and are never included in
  inventory or operation results.

## 5. Resource model

Every new typed resource follows the existing inventory identity:

```text
(provider_connection_id, provider_resource_id)
```

Administrative resources visible through several project connections require a
stable provider-level identity. CPS therefore additionally records:

- `provider_id`;
- `region_name` where applicable;
- `scope_kind`;
- `owner_domain_provider_resource_id`;
- `owner_project_provider_resource_id`.

The migration must prevent duplicate common resources when the same domain,
project, flavor, image, or external network is observed from multiple
connections. The implementation plan must choose and test one canonical
inventory owner plus visibility bindings; it must not silently merge by name.

New typed models:

- `IdentityDomain`
- `IdentityRole`
- `RoleAssignment`
- `ProjectQuota`
- `AvailabilityZone`
- `FlavorExtraSpec`
- `ImageMember`
- `Router`
- `RouterInterface`
- `SecurityGroup`
- `SecurityGroupRule`
- `FloatingIp`
- `VolumeType`
- `VolumeSnapshot`

Existing `Project`, `Flavor`, `Image`, `Network`, `Subnet`, `Port`, and
`Volume` models gain explicit owner/scope fields where required.

## 6. API and operation conventions

### 6.1 Read APIs

Inventory remains queryable using plural provider-neutral resources:

```text
GET /api/v1/identity-domains
GET /api/v1/projects
GET /api/v1/project-quotas
GET /api/v1/availability-zones
GET /api/v1/flavors
GET /api/v1/images
GET /api/v1/networks
GET /api/v1/subnets
GET /api/v1/routers
GET /api/v1/ports
GET /api/v1/security-groups
GET /api/v1/floating-ips
GET /api/v1/volume-types
GET /api/v1/volumes
GET /api/v1/volume-snapshots
```

Every list API supports allow-listed filtering by provider, connection, owner
domain/project, lifecycle state, and resource-specific safe fields. Provider
attributes remain versioned and are not a substitute for common query fields.

### 6.2 Mutation APIs

Mutations are asynchronous and return `202 Accepted`, `operation_id`,
`status_url`, and correlation ID. Representative endpoints are:

```text
POST   /api/v1/provider-connections/{id}/identity-domains
PATCH  /api/v1/identity-domains/{id}
DELETE /api/v1/identity-domains/{id}

POST   /api/v1/provider-connections/{id}/projects
PATCH  /api/v1/projects/{id}
DELETE /api/v1/projects/{id}
PUT    /api/v1/projects/{id}/quotas

POST   /api/v1/provider-connections/{id}/networks
POST   /api/v1/provider-connections/{id}/subnets
POST   /api/v1/provider-connections/{id}/routers
PUT    /api/v1/routers/{id}/interfaces/{subnet_id}
POST   /api/v1/provider-connections/{id}/security-groups
POST   /api/v1/provider-connections/{id}/floating-ips

POST   /api/v1/provider-connections/{id}/volumes
POST   /api/v1/volumes/{id}/attachments
POST   /api/v1/provider-connections/{id}/volume-snapshots
```

Destructive APIs require an explicit precondition:

- optimistic resource version or `If-Match`;
- `force=false` by default;
- dependency/conflict checks;
- deterministic already-absent behavior.

### 6.3 Commands

Commands use provider-specific routing but provider-neutral CPS request models:

```text
openstack.identity.domain.create|update|delete
openstack.identity.project.create|update|delete
openstack.identity.role_assignment.ensure|revoke
openstack.quota.update
openstack.network.create|update|delete
openstack.subnet.create|update|delete
openstack.router.create|update|delete
openstack.router_interface.ensure|remove
openstack.port.create|update|delete
openstack.security_group.create|update|delete
openstack.security_group_rule.create|delete
openstack.floating_ip.allocate|associate|disassociate|release
openstack.volume.create|update|extend|delete|attach|detach
openstack.volume_snapshot.create|update|delete
openstack.image.create|update|delete|member_grant|member_revoke
openstack.flavor.create|update|delete|access_grant|access_revoke
```

Each operation has a versioned request/result contract and golden success,
failure, replay, and tombstone fixtures.

## 7. Replay and convergence rules

Create:

- CPS idempotency uniqueness remains
  `(provider_connection_id, operation_type, idempotency_key)`.
- OPS uses a provider-supported operation marker when possible.
- When markers are unavailable, OPS searches by immutable provider identity or
  uses a deterministic provider-side request token where supported.
- Name alone is never sufficient replay evidence.

Update:

- OPS reads current provider state first.
- A request already satisfied publishes the same successful normalized result.
- Conflicting current state produces `PROVIDER_CONFLICT`.

Delete:

- already absent is idempotent success with a tombstone;
- OPS waits for provider absence or documented terminal state;
- timeout never implies deletion;
- dependency conflicts do not trigger cascading deletes unless an explicit
  future composite workflow defines them.

Composite relationships:

- router interface, floating-IP association, and volume attachment use
  ensure/remove semantics;
- replay checks both endpoints of the relationship;
- partial success is reported with safe provider state and reconciled through
  targeted refresh, not hidden.

## 8. Capability model

Capability discovery adds operation-level keys, including:

```text
identity.domain.create
identity.project.create
identity.role_assignment
quota.compute.update
quota.network.update
quota.block_storage.update
network.create
subnet.create
router.create
router.interface
port.create
security_group.create
floating_ip.allocate
volume.create
volume.snapshot
image.create
image.member
flavor.create
flavor.access
```

Every capability reports supported/unsupported plus a safe reason. OPS checks
service presence, API/microversion/extension availability, and credential
scope. CPS rejects known unsupported requests before publishing; OPS remains
the final authority immediately before provider mutation.

## 9. Security and validation

- Administrative operations require a connection whose validated scope permits
  the action; IAM enforcement is deferred, not replaced with implicit trust.
- Public API deployment remains restricted to a trusted internal network until
  IAM is integrated.
- CIDR, allocation pool, gateway, DNS, route, protocol, port range, image
  format, size, and quota values receive bounded common validation.
- CPS validates all referenced resources belong to the intended provider and
  owner scope.
- OPS repeats provider existence and ownership checks.
- Image data upload never passes through RabbitMQ. A later implementation must
  use bounded streaming or provider-supported import from an approved source.
- Private keys, passwords, tokens, `user_data`, image credentials, signed URLs,
  and raw response bodies are secrets.

## 10. Delivery slices

| Sprint | Outcome |
|---|---|
| 7 | Contract, scoped-connection, domain/project inventory and lifecycle foundation |
| 8 | Roles, assignments, quotas, availability zones, and administrative acceptance |
| 9 | Network, subnet, router, port, security-group, and floating-IP control |
| 10 | Volume/type/snapshot and image/flavor catalog control |
| 11 | Cross-resource recovery, drift, upgrade, and real-cloud release acceptance |

Sprint numbers are forecasts. Sprint Planning may move ready stories without
changing this design or their dependencies.

## 11. Design gates

Implementation must not begin until:

- this design delta is approved;
- CPS canonical request/result/error schemas for the first slice are reviewed;
- the provider connection migration and rollback plan is reviewed;
- OpenStack administrative test credentials and disposable domain/project
  naming are approved;
- cleanup ownership and quotas for real-cloud tests are documented;
- CPS and OPS backlogs contain paired stories with executable acceptance
  criteria.

