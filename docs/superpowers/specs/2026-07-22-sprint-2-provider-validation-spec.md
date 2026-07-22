# Sprint 2 Provider Validation Vertical Slice Specification

**Status:** Approved for implementation by the Sprint 2 orchestration prompt
**Date:** 2026-07-22
**Parent design:** `2026-07-16-openstack-cloud-provider-management-design.md`
**Scope:** CPS-201..206 and OPS-201..204 only

## 1. Outcome and boundaries

Sprint 2 delivers one provider-management path from CPS REST through RabbitMQ and OPS to
read-only OpenStack discovery, then back to a durable CPS operation. CPS remains the source of
truth. OPS remains stateless and never stores credentials.

The slice ends after connection validation and capability persistence. Inventory collection, VM
lifecycle, scheduling, Keycloak, MS/TMS/LMS/CMP integration, multi-region connections, additional
OpenStack authentication methods, UI work, and CI pipeline work are not part of this sprint.

## 2. Public CPS resources

All public routes are under `/api/v1`. IDs created by CPS are UUIDv7. Timestamps are UTC. Public
responses never contain username, password, ciphertext, nonce, encryption-key version, token,
session, raw service catalog, raw provider response, or credential reference unless that reference
is explicitly part of safe connection metadata.

### 2.1 Provider

`POST /api/v1/providers` accepts:

```json
{
  "name": "lab-openstack",
  "provider_type": "OPENSTACK",
  "description": "optional"
}
```

`provider_type` is exactly `OPENSTACK`. The response contains `id`, `name`, `provider_type`,
`description`, `status`, `version`, `created_at`, and `updated_at`. `PATCH
/api/v1/providers/{id}` requires `expected_version` and may change `name`, `description`, or
`status`. A referenced provider is disabled instead of physically deleted; Sprint 2 exposes no
provider DELETE route.

`GET /api/v1/providers` supports `offset` (default 0), `limit` (default 50, maximum 200), exact
`status`, exact `provider_type`, bounded `name` search, `sort` in `name|created_at|updated_at`, and
`order` in `asc|desc`. Ordering always appends `id` as a deterministic tie-breaker. List responses
use `{ "items": [], "page": {"offset": 0, "limit": 50, "total": 0} }`.

### 2.2 Credential

`POST /api/v1/credentials` accepts `username`, `password`, `user_domain_name`, and no caller-
selected key version. CPS uses the configured active key version. `PATCH /api/v1/credentials/{id}`
requires `expected_version`; it can replace username/password/domain and can rotate unchanged
secrets to the active key. `DELETE /api/v1/credentials/{id}` succeeds only when no connection
references the row.

Credential responses contain only `id`, `user_domain_name`, `version`, `created_at`, `updated_at`,
and `rotated_at`. Username and password are both AES-256-GCM encrypted at rest with independent
nonces and field-bound AAD. Missing, malformed, or wrong key material fails closed with a generic
error. The key ring is supplied through environment configuration and is never logged or returned.

The Sprint 1B migration is immutable. A new Sprint 2 Alembic revision replaces the plaintext
`username` column with encrypted username columns and adds rotation metadata. Upgrade and
downgrade are supported for an empty/disposable database; a non-empty legacy credential table
causes the destructive shape migration to fail with a safe operator message rather than copying
plaintext through migration logs or SQL literals.

### 2.3 Provider connection

`POST /api/v1/providers/{provider_id}/connections` accepts:

```json
{
  "credential_id": "uuid",
  "auth_url": "http://controller:5000/v3",
  "project_name": "admin",
  "project_domain_name": "Default",
  "region_name": "RegionOne",
  "interface": "public",
  "verify_tls": true,
  "ca_cert_pem": null
}
```

A row identifies one `(provider, project_domain_name, project_name, region_name)` tuple. Duplicate
identity is `409 PROVIDER_CONNECTION_CONFLICT`. Provider and credential must exist and be usable.
Initial status is `PENDING_VALIDATION`. `PATCH /api/v1/provider-connections/{id}` requires
`expected_version`; changing auth/scope/TLS inputs clears capabilities and validation error and
returns status to `PENDING_VALIDATION`. Disabling is explicit. Public connection responses omit the
credential reference and CA body; they expose only `has_custom_ca` for CA metadata.

`GET /api/v1/provider-connections` uses the common page shape and allow-listed filters/sorts.
`GET /api/v1/provider-connections/{id}/capabilities` returns the latest successful canonical
capability document or normalized not-found/not-yet-validated errors.

The future domain→organization and project→workspace relationship remains a documented boundary;
Sprint 2 does not create organization/workspace IDs or call MS/TMS.

## 3. Internal credential resolution

The internal route is not included in the public app/router or public OpenAPI document:

```text
GET /internal/v1/credentials/{credential_reference}
    ?provider_connection_id={provider_connection_id}
```

The two references must match one active provider, one non-disabled connection, and its referenced
credential. The response is capped at 16 KiB and contains exactly:

```json
{
  "auth_url": "http://controller:5000/v3",
  "username": "decrypted only for this response",
  "password": "<runtime-secret-omitted>",
  "user_domain_name": "Default",
  "project_name": "admin",
  "project_domain_name": "Default",
  "region_name": "RegionOne",
  "interface": "public",
  "verify_tls": true,
  "ca_cert_pem": null
}
```

No request/response/access log contains the body. The service decrypts into handler-local values,
serializes once, and does not cache or persist the response. A dedicated dependency is present for
future service authentication but is a no-op network-boundary hook in Sprint 2. Disabled or invalid
references return normalized 404/409 without revealing which component exists.

## 4. Validation command and operation

`POST /api/v1/provider-connections/{id}/validate` requires `Idempotency-Key`, accepts no secret
body, and returns HTTP 202 with the operation resource, status URL, and `X-Correlation-ID`.

In one CPS SQLAlchemy unit of work, the endpoint creates or reuses the operation, appends the
`ACCEPTED → QUEUED` event, and creates the outbox row. The canonical command is
`openstack.connection.validate`; its envelope contains
`provider_id`, `provider_connection_id`, and `credential_reference`. Its payload is only:

```json
{"validation_mode":"SAFE_READ_ONLY"}
```

The command never contains auth URL, username, password, domain, project, region, CA body, token,
or session data. Reusing an idempotency key with an equal semantic request returns the same
operation and creates no second outbox row. Reusing it with different input is `409
IDEMPOTENCY_KEY_REUSED`.

The operation is committed as `QUEUED`. Progress payloads contain an allow-listed `state` of
`RUNNING` or `WAITING_PROVIDER` plus a bounded integer progress value; the first progress event
moves it to `RUNNING` and the discovery progress event moves it to `WAITING_PROVIDER`. Terminal
completed/failed events move it to `SUCCEEDED`/`FAILED`. Terminal rows remain immutable; late events
are retained as safe late-result history. Inbox deduplication is by `(consumer_name, message_id)`.

## 5. Canonical capability document

The CPS-owned JSON Schema is version `1.0`, has a maximum serialized size of 64 KiB, and permits no
SDK objects, tokens, raw catalogs, or raw responses.

```json
{
  "schema_version": "1.0",
  "services": {
    "identity": {
      "available": true,
      "interface": "public",
      "region": null,
      "endpoint": "http://controller:5000/v3",
      "min_version": "3",
      "max_version": "3",
      "reason": null
    },
    "compute": {"available": true, "min_version": "2.1", "max_version": null},
    "network": {"available": true, "min_version": "2.0", "max_version": null},
    "image": {"available": true, "min_version": "2", "max_version": null},
    "block_storage": {"available": false, "reason": "SERVICE_NOT_AVAILABLE"}
  },
  "features": {
    "connection.authenticate": {"supported": true, "reason": null},
    "service.identity": {"supported": true, "reason": null},
    "service.compute": {"supported": true, "reason": null},
    "service.network": {"supported": true, "reason": null},
    "service.image": {"supported": true, "reason": null},
    "service.block_storage": {"supported": false, "reason": "SERVICE_NOT_AVAILABLE"}
  }
}
```

All five service keys and six feature keys are always present. Identity and compute are required for
a successful validation. Network, image, and block storage are optional and are reported unavailable
without crashing validation. Endpoints are normalized safe strings selected for the configured
interface/region. Missing optional endpoints use `reason=SERVICE_NOT_AVAILABLE`.

## 6. OPS execution boundaries

OPS resolves credentials with an `httpx.AsyncClient` using separate bounded connect/read/write/pool
timeouts, a 16 KiB response cap, and no retries inside the client. CPS timeout/network/5xx errors
normalize as retryable `CPS_UNAVAILABLE`; invalid/disabled references are non-retryable. Resolution
objects use redacted `repr`, are never cached, and exist only inside the validation handler scope.
Temporary byte buffers are overwritten where practical; Python immutable strings are released by
dropping references in `finally` blocks without claiming guaranteed zeroization.

The OpenStack factory creates `openstack.connection.Connection` with username/password auth,
project/user domains, region, interface, TLS verify or an ephemeral CA file, bounded SDK/session
timeouts, and explicit `CPS-OPS/0.1` user agent. It does not set a cloud release or fixed maximum
microversion. CA temporary files have owner-only permissions and are removed in `finally`.

Validation performs only authentication, catalog lookup, endpoint/version discovery, and safe list
or current-project probes. It never creates, updates, or deletes an OpenStack resource. SDK and
Keystone exceptions are normalized with safe provider request IDs; auth, unavailable, timeout, and
network errors use the canonical `CommonError` model.

OPS emits deterministic per-operation message IDs for `validation.started`,
`validation.discovery`, and the terminal result so command redelivery is inbox-deduplicated. The
handler returns an ordered, immutable sequence of outbound events to the command consumer. The
consumer publishes every progress and terminal event in order and receives every broker confirm
before the single command ACK. A confirm failure closes the channel and leaves the command unacked.
Handlers do not publish around the consumer. Retry/DLQ behavior remains the Sprint 1B policy.

Events omit `credential_reference`. Event trace context is redacted. Completed events contain only
`status=VALID` and the canonical capability document. Failed events contain only `CommonError`.

## 7. CPS event application

The existing inbox transaction remains the transaction owner. On successful validation completion,
one transaction:

1. deduplicates the message;
2. locks the operation and verifies provider/connection ownership;
3. validates the capability schema and size;
4. stores capabilities, clears validation error, sets connection `VALID`, and sets `validated_at`;
5. moves the operation to `SUCCEEDED` and appends immutable history;
6. marks the inbox row processed and commits.

On a terminal non-retryable authentication, authorization, or reference failure it stores only the
normalized safe error on the connection, sets `INVALID`, updates `validated_at`, moves the operation
to `FAILED`, and commits with the inbox row. A retry-exhausted unavailable/timeout/network failure
stores the safe error but leaves the connection `PENDING_VALIDATION`; a transient outage is not proof
that credentials are invalid. Progress updates operation state/progress/history but not connection
capabilities. `CommonError.details` passes the same forbidden-key/depth/size validator as operation
event details. Unknown contract versions, oversized capabilities, ownership mismatch, or unsafe
result shapes are rejected under the Sprint 1B retry/DLQ matrix.

## 8. Query and error conventions

`GET /api/v1/operations`, `GET /api/v1/operations/{id}`, and `GET
/api/v1/operations/{id}/events` use stable paging/filtering/sorting. Operation list filters are
`provider_connection_id`, exact `operation_type`, exact `state`, and created-at range. Sort is
`created_at|updated_at`, with ID tie-breaker. Event ordering is immutable `sequence ASC`; events can
be paged by offset/limit.

Operation responses preserve correlation ID, causation ID, safe actor context, and provider request
ID. Request/result/error payloads are schema-filtered before response and never contain raw provider
content or credentials. Unknown IDs return `404 OPERATION_NOT_FOUND`.

Stable public error codes include `PROVIDER_NOT_FOUND`, `CREDENTIAL_NOT_FOUND`,
`PROVIDER_CONNECTION_NOT_FOUND`, `OPERATION_NOT_FOUND`, `VERSION_CONFLICT`,
`RESOURCE_IN_USE`, `PROVIDER_CONNECTION_CONFLICT`, `IDEMPOTENCY_KEY_REUSED`,
`CREDENTIAL_KEY_UNAVAILABLE`, `PROVIDER_AUTHENTICATION_FAILED`, `PROVIDER_UNAVAILABLE`,
`PROVIDER_TIMEOUT`, and `MESSAGE_SCHEMA_UNSUPPORTED`.

## 9. Verification and real OpenStack acceptance

Unit tests cover positive behavior and every failure listed above. CPS integration tests run migration
upgrade/downgrade/upgrade, model parity, FK/unique/version races, atomic operation+outbox, inbox
capability persistence, and idempotent replay against disposable PostgreSQL 18. Messaging tests use
disposable RabbitMQ vhosts. OPS tests use SDK fakes and HTTP mock transports; deprecation warnings
are errors in focused SDK tests.

The real E2E uses the product path and the user's OpenStack lab. The Ubuntu host must resolve
`controller` to the controller VM address or use an explicitly user-approved equivalent local
resolver entry. The probe creates no OpenStack resource. Evidence records IDs, states, service
availability, request IDs, checksums, test counts, and redaction assertions, but never tokens or
credentials. Sprint 2 remains open if host routing/resolution or required connection inputs are not
available.
