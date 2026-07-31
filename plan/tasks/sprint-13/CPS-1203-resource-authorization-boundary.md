# CPS-1203 — Fail-closed resource authorization boundary

**Status:** Deferred — excluded TMS-dependent authorization scope  
**Active backlog:** No — TMS work is explicitly excluded from the current scope  
**Points:** 13  
**Depends on:** CPS-1202  
**Paired task:** OPS-1202  
**External dependency:** TMS internal authorization API, not implemented in this scope  
**Design:** `../../../docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`

## Outcome

Every user-initiated tenant-resource read or mutation derives persisted
ownership and receives an authorization decision before data disclosure,
operation creation, outbox publication, or OpenStack mutation.

## Change set

### Authorization contracts

- Define centralized compute, storage, network, image, and project permissions.
- Add `AuthorizationDecision`, outbound authorization port, stable deny,
  unavailable, malformed-response, and expired-decision errors.
- Define safe decision metadata for operation actor context.
- Never persist bearer tokens or role lists.

### CPS adapters

- Implement a strict configurable HTTP adapter for the future TMS endpoint.
- Forward the original bearer token only over the outbound call.
- Validate response schema, subject, tenant, permission, decision ID, and expiry.
- Add bounded connect/read timeouts and fail-closed error mapping.
- Implement a deterministic stub selected explicitly for test/local profiles.
- Missing production endpoint or accidental stub configuration fails startup or
  fails the request closed.

### Ownership and policy enforcement

- Add a resource ownership resolver that joins resource to canonical project in
  one indexed query.
- Ignore caller-provided org/workspace for existing resource ownership.
- Authorize get/list/create/update/action/delete before the first observable or
  durable side effect.
- Authorize list once per workspace.
- Group bulk resources by workspace and authorize once per distinct workspace;
  reject the whole atomic request if any decision denies.
- Restrict unresolved/unbound resources to CMP administrators.
- Return a non-disclosing response for cross-tenant resource lookup.

### Async operation behavior

- Store safe decision metadata in `operations.actor_context`.
- Distinguish system reconciliation from user-initiated commands.
- Reauthorize if a queued user decision expires before dispatch; otherwise fail
  without publishing.
- Send only safe decision context to OPS.

## Implementation order

1. Add failing authorization contract and permission-mapping tests.
2. Add outbound port and deterministic stub.
3. Add strict HTTP adapter and configuration validation.
4. Implement ownership resolver.
5. Apply policy to read/list APIs.
6. Apply policy before every tenant mutation/operation/outbox transaction.
7. Add decision audit and dispatch-expiry behavior.
8. Pin safe context in OPS-1202.
9. Run cross-tenant, outage, expiry, and redaction acceptance.

## Required tests

- Allow permits exactly the requested tenant action.
- Explicit deny returns `403` and creates no operation/outbox row.
- Timeout/unavailable/malformed response returns `503` and creates no side
  effect.
- Missing project mapping and disabled/unbound project deny access.
- Client cannot override persisted ownership.
- Cross-workspace get does not disclose resource existence.
- List authorizes once and filters by internal project FK.
- Bulk authorizes once per workspace and rejects atomically.
- Expired queued decision reauthorizes or fails before publish.
- JWT and role list are absent from DB, logs, messages, and errors.
- Test/local stub uses deterministic Mongo-style org/workspace IDs.
- TMS and LMS working trees remain untouched.

## Verification

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
```

## Done when

- Every tenant API path is covered by an authorization matrix test.
- CPS fails closed for all authority failures.
- OPS receives only a safe, valid decision context.
- Production configuration cannot silently use the test stub.

## Out of scope

- Implementing or modifying the TMS endpoint, guard, role model, or cache.
- LMS audit publishing.
- BMS usage authorization.
