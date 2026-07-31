# CPS Keycloak authentication plan

## Context and decisions

- CPS authenticates requests with a bearer JWT issued by the Keycloak instance in the local Docker Compose stack (`http://127.0.0.1:8080`).
- The issuer is the `vnpost` realm and the client is `cmp`.
- Authorization is derived from roles in `resource_access.cmp.roles`; CPS maps the CMP roles `admin` and `member` to its API policies. CPS does not call BMS and does not depend on BMS for identity or role lookup.
- CPS and OPS use one OpenStack admin credential for OpenStack operations. End-user Keycloak credentials are never sent to OpenStack, and OPS remains an internal adapter rather than a second end-user authentication boundary.
- Authentication and authorization are separate from business audit logging; this work must not introduce a BMS dependency.

## Delivery phases

1. **Configuration** — add `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, issuer/audience and JWKS cache settings to CPS. Keep development defaults in Compose, while secrets remain environment/secret-manager values.
2. **JWT verification middleware** — validate signature using the realm JWKS, issuer, expiry and (where configured) audience. Reject missing, malformed, expired and invalid-signature tokens with `401`.
3. **Role policy** — normalize `resource_access.cmp.roles`; grant admin-only endpoints to `admin`, member endpoints to `member` (admin may inherit member access), and return `403` for an authenticated token without a required role.
4. **Request context and API integration** — expose a typed principal to handlers, protect `/api/v1/**` and `/api/v1/admin/**`, and leave health/readiness endpoints public. Do not put tokens in logs.
5. **Tests and rollout** — add unit tests for claim extraction and policy decisions, integration tests against local Keycloak for the supplied admin/member accounts, and negative tests for wrong issuer, audience, expiry and missing roles. Roll out behind a configuration flag, then make verification mandatory.

## Acceptance criteria

- A valid `cmp:admin` token can call admin and member APIs; a valid `cmp:member` token can call only member APIs.
- No token, invalid token or wrong role receives the documented `401`/`403` response.
- CPS starts with Keycloak unavailable (JWKS is fetched/cached on demand) but fails closed when a protected request cannot be verified.
- No CPS code imports BMS authentication components or uses BMS as an identity source.
- Bruno's `CPS Local` environment can obtain admin/member tokens without storing passwords or access tokens in Git.

## Operational notes

Use Keycloak's OIDC discovery endpoint and JWKS endpoint rather than copying signing keys. Configure short-lived JWKS caching with refresh on unknown `kid`. For production, use Authorization Code + PKCE for interactive clients; password grant is retained only for the local Bruno smoke tests.
