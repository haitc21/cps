# OpenStack Cloud Provider Management Design

**Status:** Approved design
**Date:** 2026-07-16
**Services:** Cloud Provider Management Service (CPS), OpenStack Provider Service (OPS)

## 1. Purpose and first delivery scope

CPS is the provider-neutral control plane for cloud providers. OPS is a stateless OpenStack adapter. The first delivery supports OpenStack without coupling the common contracts to OpenStackSDK or prematurely implementing VMware behavior.

The two repositories are developed, deployed, and tested independently from the existing CMP services. Integration with Keycloak, MS organization, TMS workspace, and LMS audit logging is deferred. The design retains stable boundaries and context fields so those integrations can be added without replacing the core workflow.

The first delivery includes:

- Provider and provider-connection management.
- Username/password authentication scoped by user domain, project, project domain, and region.
- Connection validation, service discovery, and capability reporting.
- Inventory for region, project, flavor, image, instance, network, subnet, port, and volume.
- Full inventory reconciliation, manual targeted refresh, and refresh after operations.
- VM create, detail, start, stop, reboot, and delete.
- Image-backed local root disks and image-created Cinder root volumes.
- Durable operation tracking, idempotency, retries, duplicate handling, and normalized errors.
- REST APIs in CPS and limited internal APIs in CPS/OPS.

The first delivery excludes:

- VMware, billing, pricing, product, quota modification, and tenant orchestration.
- Keycloak authentication and authorization.
- Direct MS/TMS/LMS integration.
- Creation or management of networks, subnets, ports, security groups, key pairs, images, flavors, or volumes as standalone workflows.
- OpenStack notification-bus/event-catcher integration.
- Metrics, console access, floating-IP operations, snapshots, resize, migrate, rebuild, rescue, and shelve.
- Valkey and MongoDB usage.

## 2. Architectural decision

CPS owns the public API, common contracts, provider configuration, credentials, normalized inventory, operations, and PostgreSQL persistence. OPS owns OpenStack connectivity, discovery, collection, mapping, VM execution, waiters, and OpenStack error translation. Long-running work uses RabbitMQ. PostgreSQL is CPS's source of truth; OPS has no business database.

```text
Client --REST--> CPS --commands/inventory/results--> RabbitMQ <--consume/publish-- OPS
                   |                                                     |
                   +-- PostgreSQL                         OpenStackSDK ---+
                                                         Keystone/Nova/
                                                         Neutron/Cinder/Glance
```

Alternative designs were rejected:

- REST callbacks for long jobs make recovery and delivery guarantees harder.
- An OPS inventory database creates two sources of truth and violates the stateless-service requirement.

## 3. Responsibilities and boundaries

### 3.1 CPS

- Own provider and provider-connection lifecycle.
- Store encrypted credentials and resolve credential references for authorized OPS calls.
- Own common schemas and provider routing by `provider_type`.
- Persist normalized inventory and relationships.
- Create operations, enforce idempotency, publish commands through an outbox, and consume events through an inbox.
- Schedule full reconciliation and expose manual sync/refresh endpoints.
- Expose inventory and operation REST APIs.
- Preserve actor and tenant context for later Keycloak/TMS/LMS integration without applying tenant authorization yet.

CPS never imports OpenStackSDK types and does not contain Nova, Neutron, Cinder, Glance, or Keystone business logic.

### 3.2 OPS

- Consume OpenStack commands and resolve credentials from CPS.
- Build an OpenStackSDK connection in memory for each unit of work.
- Discover the service catalog, endpoints, supported services, API versions, and usable capabilities.
- Collect paginated inventory and map SDK resources into versioned common contracts.
- Execute VM operations and wait for provider terminal states.
- Normalize OpenStack errors while retaining safe provider request identifiers and diagnostic details.
- Publish inventory batches, progress, terminal results, and tombstones.

OPS stores no credential, inventory, tenant, product, pricing, billing, or audit state.

### 3.3 Deployment topology

- CPS and OPS deploy and scale independently.
- They use the shared CMP RabbitMQ and PostgreSQL clusters. CPS owns a separate database or schema and DB user.
- Exchanges, queues, dead-letter queues, routing keys, and permissions are isolated by domain/service.
- OPS does not require PostgreSQL, MongoDB, or Valkey.
- CPS readiness checks PostgreSQL and RabbitMQ. OPS readiness checks RabbitMQ. A failed customer OpenStack connection affects only that connection's status.

## 4. Provider, connection, and credential model

One provider connection represents exactly one OpenStack project in exactly one region. The environment may currently expose one region, but region remains explicit in the model.

OpenStack authentication is permanently limited to username/password with:

- `auth_url`
- `username`
- `password`
- `user_domain_name`
- `project_name`
- `project_domain_name`
- `region_name`
- endpoint `interface` (`public`, `internal`, or `admin`)
- TLS verification and optional CA certificate

Credentials are stored in CPS PostgreSQL for the first delivery. Sensitive values are encrypted at the application layer using a deployment key held outside the database. Public APIs never return passwords. Logs, tracing attributes, RabbitMQ messages, operation result payloads, and inventory must redact password, token, authorization header, CA private material, and VM `user_data`.

Commands contain only `credential_reference`. OPS resolves it through CPS internal REST immediately before use and retains the clear value only in process memory. This boundary permits a later secret-store implementation without changing command contracts.

The future domain-to-organization and project-to-workspace mapping is documented but not modeled or integrated now. A future workspace may map to exactly one OpenStack project on one provider connection.

## 5. Capability and compatibility model

OPS must not lock to an OpenStack release or a fixed maximum microversion. It performs version and service discovery for each connection and reports a capability document to CPS.

Capabilities include service availability and supported operations, for example:

```json
{
  "schema_version": "1.0",
  "services": {
    "identity": {"available": true},
    "compute": {"available": true, "min_version": "2.1", "max_version": "..."},
    "network": {"available": true},
    "image": {"available": true},
    "block_storage": {"available": true}
  },
  "features": {
    "instance.create.image": {"supported": true},
    "instance.create.volume_from_image": {"supported": true},
    "instance.start": {"supported": true},
    "instance.stop": {"supported": true},
    "instance.reboot": {"supported": true},
    "instance.delete": {"supported": true},
    "config_drive": {"supported": true}
  }
}
```

OPS uses the minimum microversion required by a selected feature, bounded by discovery. Unsupported functionality fails before provider mutation with `CAPABILITY_NOT_SUPPORTED`. Discovery failures do not make the OPS process unready.

## 6. Common resource model

Each inventory table has a CPS UUID and provider identity. Names are never identities.

Common fields are:

- `id`, `provider_id`, `provider_connection_id`
- `provider_resource_id`
- `name`, optional `description`
- `provider_status`
- `lifecycle_state`: `ACTIVE`, `DELETED`, or `UNKNOWN`
- `provider_created_at`, `provider_updated_at`
- `last_seen_at`, `deleted_at`, `last_sync_id`
- timestamps and optimistic-lock version
- versioned `provider_attributes`

The unique identity is `(provider_connection_id, provider_resource_id)` within each typed resource table.

Typed common data:

- Region: name/ID, description, parent region where exposed.
- Project: name/ID, domain ID/name, description, enabled.
- Flavor: vCPUs, RAM MiB, root/ephemeral disk GiB, swap MiB, public/enabled.
- Image: status, visibility, size, minimum disk/RAM, formats, checksum.
- Instance: status, normalized power state, flavor/image references, boot source, availability zone, addresses, metadata, launch/termination time.
- Network: status, admin state, shared, external, MTU.
- Subnet: network reference, CIDR, IP version, gateway, DHCP, DNS, allocation pools.
- Port: network reference, status, admin state, MAC, fixed IPs, device, owner, security-group IDs.
- Volume: status, size, type, bootable, encrypted, multiattach, availability zone, attachments.

Relationships use CPS UUIDs when available and retain provider IDs during ingestion so out-of-order batches can be resolved at finalization. Join tables represent instance-port and instance-volume relationships, including device, boot index, and delete-on-termination where known.

Provider-only data uses:

```json
{
  "provider": "OPENSTACK",
  "schema_version": "1.0",
  "data": {}
}
```

SDK objects are never serialized. Secrets and `user_data` are never inventory attributes. A provider field needed for common query or workflow must graduate to a typed common column.

## 7. Inventory synchronization and reconciliation

The design follows ManageIQ's full-refresh plus targeted-refresh pattern, simplified to avoid an OpenStack event catcher in the first delivery.

### 7.1 Full reconciliation

CPS creates an operation and `inventory_sync`, publishes `inventory.collect`, and enforces at most one active full sync per connection. OPS collects each supported resource with OpenStackSDK pagination, maps it, and publishes batches. Logical collection order is region/project, flavor/image, network/subnet, port/volume, then instance, but CPS remains safe under out-of-order delivery.

Each batch contains `sync_id`, `resource_type`, per-type `sequence`, `is_last`, `item_count`, `checksum`, and items. CPS upserts by provider identity and sets `last_sync_id`. It finalizes relationships only after required collections close.

Deletion reconciliation occurs only when:

- OPS publishes successful completion;
- every supported required collection has an `is_last` batch;
- no required collection failed; and
- checksums/counts and batch sequence are valid.

Only then are previously active rows with a different `last_sync_id` marked `DELETED`. An unsupported collection is explicitly `SKIPPED_UNSUPPORTED`; it is not treated as empty. Partial failure never deletes missing resources.

Full sync can be started manually or on a CPS-owned schedule with jitter. Schedule frequency is configuration, not a hard-coded product rule.

### 7.2 Refresh after operations and manual targeted refresh

After create/start/stop/reboot, OPS waits for the desired provider state and returns a normalized instance snapshot plus affected ports/volumes. CPS updates operation and inventory atomically. After delete, OPS waits for server absence and emits a tombstone, then refreshes affected ports/volumes.

A manual targeted-refresh endpoint accepts a supported resource type and CPS/provider resource ID. Provider `NotFound` produces a tombstone. Timeout, authorization failure, or service unavailability never imply deletion.

### 7.3 Deleted and reappearing resources

Deleted resources remain for audit and reconciliation, are hidden from lists by default, are available by ID or `include_deleted=true`, and are not physically purged by default. If the same provider ID reappears, CPS reactivates the same row and UUID while preserving operation/event history.

## 8. VM create and lifecycle operations

Every mutation creates one operation for one VM. Bulk create belongs to a future orchestration layer.

Required create inputs are name, flavor, boot source, and at least one explicit network. Explicit networks avoid ambiguous Nova auto-selection when a project has multiple networks.

Boot sources:

- `IMAGE`: image-backed local/ephemeral root disk governed by flavor; it disappears with the VM.
- `VOLUME_FROM_IMAGE`: create a Cinder root volume from an image. `delete_on_termination` defaults to true and may be false.

A future `EXISTING_VOLUME` mode will default to retaining the volume. It is not implemented now.

Optional create inputs:

- multiple existing network IDs or pre-existing port IDs where capability allows;
- existing security-group IDs;
- existing key-pair name;
- availability zone;
- free-form cloud-init `user_data`;
- `config_drive`, default false;
- metadata within provider-reported limits.

CPS validates common shape and inventory ownership. OPS revalidates provider existence/scope immediately before mutation. OPS base64-encodes `user_data` as required by Nova, never logs or inventories it, and enforces the safe/provider-discovered size limit.

The service does not create key pairs, security groups, rules, networks, ports, or volumes as standalone operations. Existing key pairs never expose private key material.

Delete delegates root-volume behavior to Nova block-device `delete_on_termination`, matching ManageIQ's lifecycle pattern; OPS does not blindly issue a second Cinder delete.

## 9. Operation state machine

Operation states are:

```text
ACCEPTED -> QUEUED -> RUNNING -> WAITING_PROVIDER -> SUCCEEDED
                          |              |
                          +--------------+-> FAILED
                          +--------------+-> TIMED_OUT
ACCEPTED/QUEUED --------------------------> CANCELLED (future API only)
```

`CANCELLED` is reserved in the schema but no cancellation endpoint is delivered initially. Terminal states are immutable except an administrative reconciliation repair, which must append an operation event.

CPS records every transition in `operation_events` with sequence, old/new state, safe details, message ID, and timestamp. This log supplies future LMS audit events. Optional `actor_context` reserves subject, organization, workspace, source service, and request context without applying authorization now.

Create and operation endpoints return `202 Accepted`, an `operation_id`, status URL, and correlation ID. Clients poll `GET /operations/{id}`. Webhooks and SSE are deferred because the durable operation model can support them later.

## 10. Transactional messaging and RabbitMQ topology

All names are configurable; logical defaults are:

- Command topic exchange: `cmp.cloud.command.v1`
- Event topic exchange: `cmp.cloud.event.v1`
- Dead-letter exchange: `cmp.cloud.dlx.v1`
- OPS queue: `ops.command.v1`
- CPS event queue: `cps.cloud.event.v1`
- OPS DLQ: `ops.command.dlq.v1`
- CPS DLQ: `cps.cloud.event.dlq.v1`

Routing keys:

- `openstack.connection.validate`
- `openstack.inventory.collect`
- `openstack.inventory.refresh`
- `openstack.instance.create|get|start|stop|reboot|delete`
- `cloud.connection.validation.progress|completed|failed`
- `cloud.inventory.batch|completed|failed`
- `cloud.operation.progress|completed|failed`

Messages and queues are durable; messages are persistent. Publishers use confirms. Consumers use manual acknowledgement and bounded prefetch. CPS uses a transactional outbox in the same DB transaction as operation creation/state changes. CPS event consumers use a transactional inbox. OPS uses message identity plus operation identity and provider-side precondition checks to make processing safe under at-least-once delivery.

### 10.1 Message envelope

```json
{
  "message_id": "uuid",
  "message_type": "openstack.instance.create",
  "schema_version": "1.0",
  "occurred_at": "RFC3339 UTC",
  "correlation_id": "uuid",
  "causation_id": "uuid-or-null",
  "operation_id": "uuid",
  "idempotency_key": "opaque-client-key",
  "provider_id": "uuid",
  "provider_connection_id": "uuid",
  "credential_reference": "uuid",
  "trace_context": {},
  "payload": {}
}
```

Events omit `credential_reference` unless strictly required; inventory events never contain it. Unknown major schema versions are rejected to DLQ and surfaced as a contract failure. Additive minor fields are ignored safely.

### 10.2 Duplicate and idempotency behavior

CPS enforces unique `(provider_connection_id, operation_type, idempotency_key)`. Repeating the same key and semantically equal request returns the existing operation. Reusing the key with different input returns `409 IDEMPOTENCY_KEY_REUSED`.

CPS inbox deduplicates `(consumer_name, message_id)`. Inventory batches also enforce `(sync_id, resource_type, sequence)`. A duplicate with a different checksum is a contract/integrity failure.

OPS keeps no database. For retries it uses operation ID, provider resource ID where known, deterministic metadata tags where supported, and provider-state preconditions. Create places the CPS operation ID/idempotency marker in permitted server metadata and searches for an existing matching server before retrying creation. A result publish failure causes command redelivery; OPS observes the existing provider state and republishes the same terminal result instead of repeating the mutation.

## 11. Error model, timeout, and retry

The common error response/event is:

```json
{
  "code": "PROVIDER_AUTHENTICATION_FAILED",
  "message": "safe human-readable message",
  "category": "AUTHENTICATION",
  "retryable": false,
  "provider": "OPENSTACK",
  "provider_service": "compute",
  "provider_request_id": "safe request id",
  "details": {},
  "occurred_at": "RFC3339 UTC"
}
```

Categories and representative codes:

- Validation: `INVALID_REQUEST`, `RESOURCE_REFERENCE_INVALID`.
- Capability: `CAPABILITY_NOT_SUPPORTED`, `SERVICE_NOT_AVAILABLE`.
- Authentication/authorization: `PROVIDER_AUTHENTICATION_FAILED`, `PROVIDER_FORBIDDEN`.
- Resource: `PROVIDER_RESOURCE_NOT_FOUND`, `PROVIDER_CONFLICT`, `INVALID_RESOURCE_STATE`.
- Capacity/quota: `QUOTA_EXCEEDED`, `INSUFFICIENT_CAPACITY`.
- Transient: `PROVIDER_RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, `PROVIDER_TIMEOUT`, `NETWORK_ERROR`.
- Internal/contract: `MESSAGE_SCHEMA_UNSUPPORTED`, `MESSAGE_INTEGRITY_ERROR`, `INTERNAL_ERROR`.

OPS maps the OpenStackSDK exception hierarchy and safe response data. Raw response bodies are not returned indiscriminately. HTTP/provider request IDs are preserved for support.

Retry rules:

- Retry connection failures, selected 5xx responses, 429/rate limiting, and transient service-unavailable errors with exponential backoff plus jitter.
- Respect `Retry-After` where present.
- Do not retry validation, authentication, authorization, not-found (except eventual-consistency reads), conflict caused by invalid state, or quota failures.
- Provider mutations are retried only after an idempotency/precondition check.
- Waiter polling is not counted as command retry.
- Exhausted transient retry produces a terminal `FAILED` or `TIMED_OUT` result; poison/contract messages go to DLQ.

Timeouts are layered and configurable: connect/read request timeout, per-service operation timeout, waiter interval, total operation deadline, and message processing deadline. OPS never waits indefinitely. CPS reconciliation marks an operation timed out when no terminal event arrives by `timeout_at`; a later provider result is retained as a late event and requires deterministic reconciliation rather than silently rewriting a terminal state.

## 12. CPS REST API

Base path: `/api/v1`. Public endpoints initially have no authentication and must be deployed on a trusted/internal network. An authorization dependency boundary remains in the API layer for later Keycloak integration.

Provider and connection endpoints:

- `POST /providers`
- `GET /providers`, `GET /providers/{id}`
- `PATCH /providers/{id}`
- `POST /providers/{id}/connections`
- `GET /provider-connections`, `GET /provider-connections/{id}`
- `PATCH /provider-connections/{id}`
- `POST /provider-connections/{id}/validate` → operation
- `POST /provider-connections/{id}/inventory-syncs` → operation
- `GET /provider-connections/{id}/capabilities`

Credential endpoints:

- `POST /credentials`
- `PATCH /credentials/{id}`
- `DELETE /credentials/{id}` only when unreferenced

Credential responses contain metadata only.

Inventory endpoints:

- `GET /regions|projects|flavors|images|instances|networks|subnets|ports|volumes`
- `GET /{resource-type}/{id}`
- `POST /{resource-type}/{id}/refresh` for supported targeted refresh

List filters include `provider_connection_id`, lifecycle/provider status, exact provider resource ID, and bounded name search. Sort fields are allow-listed (`name`, `created_at`, `updated_at`) with stable ID tie-breaking. Pagination uses a uniform offset/limit representation initially; the response shape can later support cursor metadata without changing resource objects. `include_deleted` defaults false.

VM operations:

- `POST /instances` → create operation
- `POST /instances/{id}/actions/start`
- `POST /instances/{id}/actions/stop`
- `POST /instances/{id}/actions/reboot`
- `DELETE /instances/{id}`

Operation endpoints:

- `GET /operations`
- `GET /operations/{id}`
- `GET /operations/{id}/events`

Every mutation accepts `Idempotency-Key` and propagates/returns `X-Correlation-ID`. Validation uses structured Pydantic errors mapped to the common error envelope.

## 13. Internal APIs

CPS internal API:

- `GET /internal/v1/credentials/{reference}` for OPS credential resolution.
- Health/live/readiness endpoints.

The credential endpoint is never exposed through public ingress. Service authentication is deferred with the broader CMP integration, but network policy and separate internal routing are mandatory from the first deployment.

OPS internal API is deliberately small:

- `/health/live`
- `/health/ready`
- optional `/internal/v1/capabilities` for service build/handler capability diagnostics, not connection-specific provider truth.

Long-running provider work is not exposed as synchronous OPS REST. RabbitMQ is the authoritative command path.

## 14. PostgreSQL model

CPS uses SQLAlchemy and Alembic with typed tables rather than a single EAV inventory table.

Core tables:

- `providers`: UUID, name, type, description, active/disabled status, timestamps.
- `provider_connections`: provider/credential FKs, OpenStack scope/config, validation status, capabilities JSONB, validation error/time, optimistic version.
- `credentials`: encrypted username/password, encryption-key version, rotation time, timestamps/version.

Inventory tables:

- `regions`, `projects`, `flavors`, `images`, `instances`, `networks`, `subnets`, `ports`, `volumes`.
- Each contains common identity/lifecycle/audit columns and typed resource columns.
- `instance_ports` and `instance_volumes` retain relationship attributes.

Sync tables:

- `inventory_syncs`: connection, operation, `FULL|TARGETED`, state, start/end, expected/completed/skipped/failed collection summaries, error summary.
- `inventory_batches`: sync, message, resource type, sequence, last marker, count, checksum, processing state/error.

Operation tables:

- `operations`: type, target, state/progress, safe request/result, normalized error, IDs/context, timestamps/deadline/version.
- `operation_events`: ordered immutable transition/progress history.

Reliability tables:

- `outbox_messages`: aggregate, message/routing type, payload, attempt schedule, publish state.
- `inbox_messages`: consumer/message identity, type, receive/process state/error.

Indexes cover provider identity, active lifecycle lists, provider status, updated/name list ordering, operation state/time, idempotency, outbox scheduling, and sync/batch uniqueness. Foreign keys use restrictive deletion for provider/credential configuration and appropriate cascade only for owned metadata such as operation events. Inventory is soft-deleted.

## 15. Source layout

The layout uses focused modules with ports/adapters boundaries.

CPS:

```text
cps/
  pyproject.toml
  alembic/
  src/cps/
    main.py
    config.py
    api/
      dependencies.py
      errors.py
      routers/{providers,connections,credentials,inventory,instances,operations}.py
    domain/
      providers/
      inventory/
      operations/
      messaging/
    application/
      commands/
      queries/
      services/
    contracts/
      api/
      messages/
      fixtures/
    infrastructure/
      db/{models,repositories,unit_of_work}.py
      messaging/{publisher,consumers,outbox,inbox}.py
      crypto/
      scheduling/
    observability/
  tests/{unit,integration,contract,e2e}/
```

OPS:

```text
ops/
  pyproject.toml
  src/ops/
    main.py
    config.py
    api/health.py
    application/
      handlers/{connection,inventory,instance}.py
      credential_resolver.py
    contracts/
      messages/
      fixtures/
    openstack/
      connection_factory.py
      capabilities.py
      collectors/{identity,compute,network,image,volume}.py
      mappers/{region,project,flavor,image,instance,network,subnet,port,volume}.py
      operations/{create,start,stop,reboot,delete,detail}.py
      waiters.py
      errors.py
    messaging/{consumer,publisher,deduplication}.py
    observability/
  tests/{unit,integration,contract,e2e}/
```

CPS is the source of truth for JSON Schema/OpenAPI contracts. OPS keeps a pinned copy with `schema_version`. No shared Python package or schema registry is introduced initially. Cross-repository contract fixtures detect drift. A package can be extracted when a second provider makes manual synchronization costly.

### 15.1 Python and dependency compatibility baseline

Both services use CPython 3.12. Python 3.14 is not used even when available on a developer workstation because the selected OpenStackSDK release officially declares and tests Python 3.11 and 3.12. Development, CI, and runtime containers must use the same Python 3.12 minor line.

The initial direct-dependency baseline, verified against published package metadata on 2026-07-17, is:

| Component | Baseline | Service | Rationale |
|---|---:|---|---|
| CPython | `3.12` | CPS, OPS | Newest Python line explicitly classified by OpenStackSDK 4.17 |
| OpenStackSDK | `4.17.0` | OPS | Current SDK; requires Python 3.11+ and declares 3.11/3.12 |
| FastAPI | `0.139.0` | CPS, OPS health API | Current Pydantic-v2-compatible API framework |
| Pydantic | `2.13.4` | CPS, OPS | Common API/message validation and JSON Schema generation |
| pydantic-settings | `2.13.x` | CPS, OPS | Typed environment configuration |
| SQLAlchemy | `2.0.51` | CPS | SQLAlchemy 2 async/session model |
| Alembic | `1.18.5` | CPS | SQLAlchemy schema migrations |
| psycopg | `3.3.4` with pool/binary extras | CPS | PostgreSQL 18-capable async/sync driver; do not use psycopg2 |
| aio-pika | `10.0.1` | CPS, OPS | Python 3.11+ async RabbitMQ client with robust reconnect and publisher confirms |

Patch versions are resolved and committed in a lockfile rather than floating at deployment time. `pyproject.toml` declares compatible release ranges for libraries that follow semantic versioning; the lockfile pins the exact transitive graph. Major/minor upgrades require unit, contract, integration, migration, and real-OpenStack smoke tests before the lockfile is refreshed.

Runtime images use an explicit Python 3.12 slim digest or immutable patch tag. They must include only OS packages required by the resolved wheels and TLS/CA handling. CPS and OPS maintain separate lockfiles because OpenStackSDK and database dependencies belong to different services. CI tests the locked dependencies against PostgreSQL 18, RabbitMQ 4.1, Valkey 9.1.0 where applicable, and the available customer OpenStack API through discovery rather than release-specific assumptions.

OpenStack compatibility is governed by service catalog discovery, negotiated API/microversions, capability tests, and SDK behavior—not by matching the Python/OpenStack release name. OPS must not depend on deprecated `python-openstacksdk`, direct Nova/Neutron/Cinder client libraries, or SDK internals when a supported OpenStackSDK proxy/resource API exists.

## 16. Observability and future audit

Structured logs include service, message/operation/correlation IDs, provider connection, resource type/ID, attempt, duration, and normalized error code. Secret filters apply before serialization. Metrics cover API latency/error, operation state/duration, queue lag/redelivery/DLQ, outbox backlog, sync counts/duration/items, provider call latency/error, and waiter outcomes.

Tracing propagates W3C trace context through REST and message headers where supported. Provider request IDs are attached to operation diagnostics.

Future LMS integration consumes operation events rather than scraping logs. The operation history therefore preserves actor context, action, target, old/new state, outcome, correlation ID, safe error, and timestamp. No direct LMS dependency is added now.

## 17. Testing strategy

### 17.1 Unit tests

CPS unit tests cover validation, state transitions, idempotency-key reuse, lifecycle reconciliation, relation resolution, error serialization, crypto boundary, filtering/pagination, and outbox/inbox logic.

OPS unit tests use SDK fakes/mocks for mapping every resource, pagination, capability discovery, exception normalization, retry classification, waiter terminal/timeout states, create payloads, volume lifecycle, redaction, and replay-safe handlers.

### 17.2 Contract tests

- Validate every command/event fixture against its JSON Schema in both repositories.
- Golden fixtures cover every inventory type and operation/error event.
- Verify OPS output is accepted by CPS models.
- Verify additive compatible fields and reject unsupported major versions.
- Detect divergent copied contract checksums in CI.

### 17.3 Integration tests

CPS integration tests use PostgreSQL and RabbitMQ containers for migrations, constraints, transactions, concurrent idempotency, outbox confirms, inbox duplicates, out-of-order batches, incomplete sync safety, and redelivery.

OPS integration tests use RabbitMQ plus mocked HTTP/OpenStack endpoints to verify credential resolution, OpenStackSDK requests, retry/redelivery, provider state preconditions, and result publication.

### 17.4 End-to-end acceptance

Against a real supported OpenStack environment:

1. Create and validate a provider connection.
2. Full-sync every scoped inventory type.
3. Create one VM using image/local root and one using volume-from-image.
4. Read detail, start, stop, reboot, and delete.
5. Poll each operation to a durable terminal state.
6. Replay a command/idempotency key without repeating provider mutation.
7. Modify/delete a resource directly in OpenStack and verify full reconciliation converges.
8. Restart CPS/OPS during work and verify no lost operation, safe redelivery, and eventual terminal state.

## 18. Open-source patterns adopted and rejected

### Adopted from ManageIQ Core and OpenStack provider

- Provider aggregate and separate authentication records.
- Capability declarations with unsupported reasons.
- Collector → parser/mapper → persister boundary.
- Full refresh plus targeted refresh and relationship expansion.
- Durable task/request state and worker callbacks, represented here by operations and result events.
- Provider identity (`ems_ref`) separated from internal identity.
- Disconnected/archived lifecycle rather than immediate physical deletion.
- Volume `delete_on_termination` delegated to Nova block-device lifecycle.

Relevant files actually inspected include ManageIQ Core `ext_management_system.rb`, `authentication.rb`, `authentication_mixin.rb`, `supports_feature_mixin.rb`, `miq_task.rb`, `base_manager/refresher.rb`, and inventory persister builders; and OpenStack provider `manager_mixin.rb`, manager/refresher classes, inventory collectors/parsers/persisters/target collections, event target parsers, VM operations, provisioning cloning/volume attachment/workflow, and their targeted-refresh/provision specs.

### Adopted from OpenStackSDK

- Connection/session and service-proxy boundaries.
- Service catalog/version discovery and configurable microversions.
- Generator pagination and typed resources.
- Waiters with timeout/failure states.
- Exception hierarchy and provider request IDs.
- Native create-server inputs for networks, ports, security groups, key pairs, user data, config drive, and block-device mappings.

Relevant modules inspected include `connection.py`, `proxy.py`, `resource.py`, `exceptions.py`, compute/network/image/identity/block-storage proxies, `cloud/_compute.py`, and unit tests for create-server behavior.

### Adopted from Apache Libcloud

- Small common provider interface and driver registry.
- Common resource identity with provider-specific extensions.
- Normalized errors retaining provider context.

Relevant modules inspected include `compute/base.py`, `compute/providers.py`, `compute/types.py`, `common/providers.py`, `common/types.py`, and the OpenStack driver/common modules.

### Explicitly rejected from ManageIQ

- Rails monolith boundaries, ActiveRecord STI/polymorphic schema, appliance roles/zones, and `MiqQueue` implementation.
- Automate workflows, UI provisioning dialogs, broad inventory unrelated to the delivery scope, metrics, chargeback, policy/compliance, SmartState, and OpenStack control-plane InfraManager.
- Direct OpenStack notification-bus consumption in the first delivery.

These omissions preserve the proven concepts without importing monolith coupling or unrelated product scope.

## 19. Evolution path

- Keycloak: implement the reserved API authorization dependency and populate actor context.
- MS/TMS: bind organization/domain and workspace/project at CPS, leaving OPS provider-scoped.
- LMS: publish audit events derived from immutable operation events through an outbox.
- Secret store: replace CPS credential repository implementation without changing command references.
- VMware: add provider contracts/capabilities and a stateless provider service with its own queues.
- Provider events: add event-driven targeted refresh while retaining full reconciliation as the convergence safety net.
- Shared contracts package: extract only when multiple provider services make pinned schema copies costly.

## 20. Acceptance of design

This design prioritizes rapid delivery while preserving product-grade boundaries, durable state, compatibility discovery, reliable messaging, and an incremental path to the wider CMP. Implementation must not expand the first-delivery scope without a corresponding design change.
