# CPS API path and authorization normalization plan

## Goal

Make the public CPS API follow one unambiguous URL convention and enforce the
Keycloak role at the route boundary:

- `/api/v1/**` is the member API and accepts only the canonical `member` role.
- `/api/v1/admin/**` is the CMP administration API and accepts only the
  canonical `admin` role.
- `/health/**` and `/metrics` remain public; the internal listener remains a
  separate service boundary.

## Route classification

1. Inventory and consumer operations (resource listing, capabilities, async
   instance/network/volume/snapshot actions and operation polling) stay under
   `/api/v1`.
2. Provider onboarding and administration (provider CRUD, credentials,
   provider connections, validation, inventory synchronization, catalogs,
   quotas, role assignments and other control-plane configuration) move under
   `/api/v1/admin`.
3. Routes must use a single router prefix rather than repeating hard-coded
   `/api/v1` fragments. Resource names are plural kebab-case; identifiers and
   action suffixes use the existing documented names.
4. Status URLs returned in accepted-operation responses must use the same
   normalized prefix as their operation endpoint.

## Implementation phases

1. Build a route inventory from FastAPI's registered routes and the CPS specs;
   classify every endpoint and record the old/new path in tests and docs.
2. Refactor router prefixes and `main.py` registration so the generated OpenAPI
   document contains only the normalized paths. Do not leave duplicate legacy
   routes unless an explicit compatibility test requires them.
3. Apply role dependencies at the router boundary in addition to the bearer
   middleware: member routers require `member`; admin routers require `admin`.
   Ensure an admin token cannot call member endpoints and vice versa.
4. Update route tests, OpenAPI/path contract tests, Bruno CPS requests and
   documentation. Verify 401 for no/invalid token and 403 for the wrong role.
5. Run the complete CPS test, lint, type-check and contract suites, then review
   the final route table for accidental unprotected or misclassified paths.

## Acceptance criteria

- Every non-health public route is under exactly one of `/api/v1` or
  `/api/v1/admin`.
- No admin endpoint is reachable through a member path and no member endpoint is
  reachable through an admin path.
- OpenAPI, status URLs, tests and Bruno collection agree with the route table.
- Authentication is mandatory in every environment; no auth-disable setting is
  introduced.
