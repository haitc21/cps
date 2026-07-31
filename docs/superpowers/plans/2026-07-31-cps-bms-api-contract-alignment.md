# CPS/BMS API contract alignment plan

## Objective

Make every CPS public API response follow the CMP/BMS contract while preserving
the existing CPS domain and asynchronous operation semantics. This is a wire
contract migration, not a change to OpenStack or Keycloak behavior.

## Reference contract learned from BMS

BMS uses a generic `BaseResponse<T>` envelope with the ordered fields:

```json
{
  "statusCode": 200,
  "errorCode": null,
  "message": "Success",
  "timestamp": "2026-07-31T00:00:00Z",
  "path": null,
  "data": {}
}
```

Errors use the same envelope with a machine-readable `ErrorCode`, HTTP status,
request path and structured `data`. Validation data is shaped as
`{"fields": {"field": [{"code", "value", "params"}]}}`. BMS separates the
HTTP status from the stable error code and keeps error messages safe for clients.

Paged responses use `data: {items, page, limit, total, totalPages}` with a
1-based page number. CPS currently exposes `{items, page: {offset, limit,
total}}` directly, so the migration must define the offset-to-page mapping and
update clients deliberately.

## Current CPS gaps

- Public success payloads are returned directly instead of inside `data`.
- CPS errors use `error: {code, category, retryable, ...}` plus a sibling
  `correlation_id`, rather than BMS `statusCode/errorCode/message/timestamp/path/data`.
- `ErrorCategory` and ad-hoc string codes are not a single catalog with a
  default message and HTTP status like BMS `ErrorCode`.
- FastAPI validation errors omit field-level violations and parameter details.
- Page DTOs use offset metadata and are inconsistent across resource families.
- OpenAPI schemas and Bruno examples describe the CPS shape rather than the
  shared CMP shape.

## Implementation phases

1. **Contract model** — introduce a Pydantic `BaseResponse[T]`, `PagedData[T]`,
   `PageMetadata`, `FieldViolation`, and a CPS `ErrorCode` enum. Use camel-case
   aliases (`statusCode`, `errorCode`, `totalPages`) and UTC timestamps. Keep
   internal messaging/database schemas unchanged.
2. **Error taxonomy** — map existing CPS exceptions to stable codes and HTTP
   statuses (`BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`,
   `CONFLICT`, `VALIDATION_FAILED`, `EXTERNAL_SERVICE_ERROR`, `INTERNAL_ERROR`)
   plus namespaced CPS domain codes such as `PROVIDER_001`, `CONNECTION_001`,
   `OPERATION_001`, `CAPABILITY_001`. Define the catalog in one place and
   forbid leaking provider credentials, tokens, stack traces or raw upstream
   responses.
3. **Exception boundary** — rewrite FastAPI handlers for domain errors,
   validation errors, authentication/authorization, 404, upstream failures and
   unexpected exceptions to emit only `BaseResponse`. Preserve correlation IDs
   in headers; if retained in the body, place them under `data` consistently.
4. **Success boundary** — wrap every public CPS response, including `200`,
   `201`, and `202 ValidationAccepted`, in `BaseResponse`. Adapt paged endpoints
   to the BMS shape; decide whether to accept legacy `offset` while emitting
   canonical `page`/`limit`, and document the deprecation window.
5. **OpenAPI/client migration** — update response models, standard response
   components, route docs and Bruno CPS requests. Add examples for admin/member
   success, validation, auth, not-found, conflict and provider errors.
6. **Compatibility and rollout** — add contract tests that compare serialized
   JSON (including null omission/order-independent aliases), snapshot the OpenAPI
   schemas, and run CPS/OPS integration tests. Release behind an explicit API
   contract version or coordinated client rollout; do not silently serve two
   incompatible envelopes on the same path.

## Acceptance criteria

- Every CPS public success and error response has the BMS envelope fields and
  no legacy top-level `error` object.
- `errorCode` is stable and catalogued; HTTP status and `statusCode` agree.
- Validation errors expose field/code/value/params without secrets.
- Paged responses contain `items`, `page`, `limit`, `total`, `totalPages`.
- Admin/member auth failures remain `401`/`403` inside the same envelope.
- Internal endpoints, RabbitMQ messages, database records and OPS adapter
  contracts are not accidentally wrapped or changed.
- OpenAPI and Bruno examples are generated from and verified against the same
  models.

## Rollout notes (implemented 2026-07-31)

- Public `/api/v1` responses use `BaseResponse` with catalogued `errorCode`
  values; legacy top-level `error` is removed from HTTP responses.
- List endpoints accept legacy `offset` **or** 1-based `page` (mutually
  exclusive) and always return `items`, `page`, `limit`, `total`, `totalPages`
  under `data`. Mapping: `page = (offset // limit) + 1`.
- `/health/*`, `/metrics`, and `/internal/v1/*` remain outside the envelope.
