# CPS-1203 — Fail-closed resource authorization boundary

**Status:** Done — ingress TMS scope authorization slice complete  
**Active backlog:** No — synchronous public-API authorization boundary is
delivered and verified; persisted decision metadata and queued-decision expiry
remain follow-up work outside this slice.  
**Points:** 13  
**Depends on:** CPS-1202  
**Paired task:** OPS-1202  
**External dependency:** Existing TMS role-read APIs (no TMS repository changes)  
**Design:** `../../../docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`  
**Plan:** `../../../docs/superpowers/plans/2026-08-04-CPS-1203-tms-scope-authorization.md`  
**Runbook:** `../../../docs/runbooks/live-cps-tms-scope-authorization-20260804.md`

## Delivered slice (2026-08-04)

CPS authenticates every protected public request with Keycloak, enforces exact
client-role route policy (`admin:admin` for `/api/v1/admin/**`, `member` for
other `/api/v1/**`), optionally bypasses route-role and TMS checks for a
configured `APP_OWNER` matched from verified JWT identity, and fail-closed
validates member organization/workspace scope through synchronous TMS role reads
before entering a member handler.

Integrated TMS endpoints (existing, read-only):

- `GET /organizations/{org_id}/members/{subject}/roles`
- `GET /organizations/{org_id}/workspaces/{workspace_id}/members/{subject}/roles`

Membership logic: non-empty `org:owner` in organization roles authorizes the
organization and its workspaces; otherwise a non-empty workspace role list
establishes membership. Member requests require non-empty `X-Org-ID` and
`X-WS-ID` headers unless the caller is `APP_OWNER`. Explicit deny/not-found
returns `403`; timeout, network failure, TMS 5xx, or malformed response returns
`503`. Bearer tokens are forwarded to TMS only and never logged, persisted,
returned, or published.

Not delivered in this slice (do not claim):

- Per-resource ownership resolver and authorization before every tenant
  read/mutation/outbox side effect.
- Persisted `AuthorizationDecision` metadata in `operations.actor_context`.
- Queued-decision expiry and reauthorization before dispatch.
- OPS safe decision context publication (OPS-1202 follow-up).

## Outcome (full design — partial delivery)

Every user-initiated tenant-resource read or mutation derives persisted
ownership and receives an authorization decision before data disclosure,
operation creation, outbox publication, or OpenStack mutation. The ingress
slice above is the first fail-closed TMS boundary; resource-level enforcement
remains follow-up work.

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

## Done when (ingress slice)

- [x] Protected public routes enforce Keycloak JWT, exact client roles, optional
  `APP_OWNER` bypass, and TMS organization/workspace membership via scope
  headers.
- [x] CPS fails closed for deny, missing scope headers, and TMS authority
  failures without handler, operation, commit, or outbox side effects.
- [x] Focused auth suite, affected integration suite, full pytest, Ruff, mypy,
  compose validation, and live positive/negative/TMS-outage recovery checks pass.
- [x] Independent Luna review approved with no findings (2026-08-04).
- [ ] Resource-level ownership resolver, persisted decision metadata, and OPS
  safe decision context remain follow-up (OPS-1202 / later CPS work).

## Out of scope

- Implementing or modifying the TMS endpoint, guard, role model, or cache.
- LMS audit publishing.
- BMS usage authorization.
