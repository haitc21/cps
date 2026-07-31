# CPS Keycloak authentication plan

## Context and decisions

- CPS authenticates requests with a bearer JWT issued by the Keycloak instance in the local Docker Compose stack (`http://127.0.0.1:8080`).
- The issuer is the `vnpost` realm and the client is `cmp`.
- Authorization is derived from roles in `resource_access.cmp.roles`; CPS maps the CMP roles `admin` and `member` to its API policies. During migration, the normalizer should accept the deployed aliases `admin:admin` and `member:signature` as equivalent policy inputs, then expose only canonical `admin`/`member` in the request context. CPS does not call BMS and does not depend on BMS for identity or role lookup.
- CPS and OPS use one OpenStack admin credential for OpenStack operations. End-user Keycloak credentials are never sent to OpenStack, and OPS remains an internal adapter rather than a second end-user authentication boundary.
- Authentication and authorization are separate from business audit logging; this work must not introduce a BMS dependency.

## Delivery phases

1. **Configuration** — add `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, issuer/audience and JWKS cache settings to CPS. Keep development defaults in Compose, while secrets remain environment/secret-manager values.
2. **JWT verification middleware** — validate signature using the realm JWKS, issuer, expiry and (where configured) audience. Reject missing, malformed, expired and invalid-signature tokens with `401`.
3. **Role policy** — normalize `resource_access.cmp.roles`; grant `/api/v1/admin/**` only to `admin` and `/api/v1/**` only to `member`. Admin and member surfaces are separate; return `403` for an authenticated token without the route's required role.
4. **Request context and API integration** — expose a typed principal to handlers, always protect `/api/v1/**` and `/api/v1/admin/**` on the public app, and leave health/readiness endpoints public. The internal listener remains unauthenticated. Do not put tokens in logs.
5. **Tests and rollout** — add unit tests for claim extraction and policy decisions, integration tests against local Keycloak for the supplied admin/member accounts, and negative tests for wrong issuer, audience, expiry and missing roles. Public API JWT verification is mandatory in every environment; there is no disable flag.

## Acceptance criteria

- A valid `cmp:admin` token can call admin APIs only; a valid `cmp:member` token can call member APIs only.
- No token, invalid token or wrong role receives the documented `401`/`403` response.
- CPS starts with Keycloak unavailable (JWKS is fetched/cached on demand) but fails closed when a protected request cannot be verified.
- No CPS code imports BMS authentication components or uses BMS as an identity source.
- Bruno's `CPS Local` environment can obtain admin/member tokens without storing passwords or access tokens in Git.

## Operational notes

Use Keycloak's OIDC discovery endpoint and JWKS endpoint rather than copying signing keys. Configure short-lived JWKS caching with refresh on unknown `kid`. For production, use Authorization Code + PKCE for interactive clients; password grant is retained only for the local Bruno smoke tests.
