# CPS-1702 — Instance console access

**Status:** Needs threat review
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

