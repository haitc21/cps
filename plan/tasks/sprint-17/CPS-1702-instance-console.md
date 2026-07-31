# CPS-1702 — Instance console access

**Status:** Superseded — durable operation boundary is not safe for bearer console credentials
**Active backlog:** no — requires a separately approved ephemeral-access architecture
**Points:** 5
**Depends on:** CPS-403, CPS-1203
**Paired task:** OPS-1702

## Outcome

An authorized user obtains short-lived console access without persisting its
bearer URL or token.

## Design constraints

- Use a dedicated synchronous/ephemeral internal response boundary; do not put
  console credentials in durable operation results, outbox, inbox, or audit.
- Enforce ownership, capability, TTL, one-user response scope, redaction, and
  no-cache behavior.
- Return unsupported when the provider cannot issue the approved console type.

## Required tests

- Allow/deny/unavailable/expired authorization.
- URL/token absent from DB, logs, metrics, traces, fixtures, and errors.
- Provider timeout and capability unsupported.

## Done when

Threat review approves the response boundary and live access expires as
documented.

## Deferred note

Console access chưa nằm trong ưu tiên hiện tại. Khi kích hoạt lại, task phải
hoàn thiện threat review và ephemeral response boundary trước khi triển khai;
console URL/token được xem như bearer secret và không được lưu trong operation
history, database hoặc log.

## Supersession decision

The current CPS-to-OPS boundary is asynchronous RabbitMQ with durable outbox,
inbox, operation result, and event history. OPS exposes no authenticated
synchronous internal endpoint for a one-user secret response. Therefore this
story cannot satisfy its own non-persistence requirement by adding another
instance action: the Nova console URL/token would necessarily enter durable
message or operation payloads.

This task is superseded rather than marked Done. A future console feature must
start with a separately approved threat model and ephemeral-access design that
defines:

- authenticated and authorized service-to-service ingress;
- instance ownership validation without returning the secret to another user;
- an in-memory-only response path with `Cache-Control: no-store`;
- bounded provider timeout and an explicit maximum TTL;
- capability negotiation for an approved console type;
- structured redaction tests for HTTP access logs, exceptions, traces, and
  metrics;
- live proof that the provider URL expires.

No console command, route, schema, or fixture is added by CPS-1702. This avoids
creating a bearer-secret persistence path while removing the deferred item
from active sprint accounting.
