# Sprint 19 portal parity — CPS/OPS-1906 evidence

Date: 2026-08-04 (Asia/Bangkok)

## Scope

CPS-1906/OPS-1906 adds additive read-only catalog presentation semantics:
allow-listed filters and deterministic sorting, safe member metadata, scoped
member catalog lookup, guarded actions/capabilities, and normalized image/flavor
provider status. No provider resource was created or mutated.

Horizon provenance was reviewed from the Apache-2.0 `openstack_dashboard/api`
Nova/Glance list/detail/access semantics. Django, Horizon runtime, novaclient,
glanceclient, image bytes, and provider credentials are intentionally excluded.

## Automated evidence

- CPS focused after remediation: `10 passed`.
- OPS focused inventory: `24 passed`.
- CPS full suite after remediation: `653 passed, 182 skipped`.
- OPS full suite: `472 passed, 24 skipped`.
- Changed-file mypy: CPS and OPS passed.
- Ruff format/check, contract validation, and `git diff --check`: passed.
- No migration was required; changes use existing JSONB/typed columns.

## Live evidence and limitation

- Controller precheck over SSH to `192.168.122.253`: OpenStack CLI `8.2.0`;
  read-only flavor/image listing succeeded.
- CPS/OPS were started directly on the host. PostgreSQL, RabbitMQ, and Keycloak
  remained the only container dependencies; RabbitMQ host mapping was `5673`.
- Debug runtime was isolated from Docker: CPS used `cmp_cps_dev`, Docker keeps
  `cmp_cps`; CPS public/internal listeners were `:8000`/`:8002`, and OPS used
  RabbitMQ host port `5673` plus CPS internal `:8002`.
- A fresh project-scoped debug connection was created and validated through
  CPS. Validation operation `019fcaac-f9d2-7af6-9ee5-247bac23967d` reached
  `SUCCEEDED`.
- Inventory operation `019fcab1-a5ae-723f-a940-9922ed6152ca`, correlation
  `f178bcd3-9ae3-47bc-9803-4f11ca8733be`, reached `SUCCEEDED` through the
  direct CPS/OPS workers and RabbitMQ. OPS resolved credentials through CPS
  internal HTTP and then queried OpenStack.
- Independent OpenStack CLI comparison: provider returned 2 images and 3
  flavors; CPS persisted 2 images/3 flavors, of which 1 image and 2 flavors
  were catalog-approved and exposed by the catalog endpoint. IDs and names
  matched the provider CLI output for the approved subset.
- The earlier system-scoped trace exposed a provider policy limitation:
  Glance `GET /v2/images` returned `403` request ID
  `req-39de122b-bd91-4817-8be3-54ab3fef6d52`, and Nova flavor extra-specs
  request returned `403` request ID
  `req-15b29240-acca-40c0-bcd1-e27d20e316f6`. Controller logs confirmed both;
  the project-scoped retry returned `200` and completed the expected catalog
  slice. The OpenStack CLI used a project-scoped admin session as well.
- No OpenStack resource was created or mutated; only debug-database provider
  configuration and inventory rows were created.
- Fresh direct-host probe (2026-08-04): CPS public/internal listeners and the
  OPS worker were started from the host using CPS/OPS `.env` files. CPS health
  returned 200 and OPS resolved both connections through the CPS internal
  endpoint. The project-scoped connection returned 3 flavors and 2 images;
  the system-scoped connection returned 3 flavors but Glance image listing
  failed with 403, request ID
  `req-d3317a33-3e88-464a-9549-71befb5b1d4a`. The independent controller CLI
  comparison matched the same result: project scope returned 3 flavors/2
  images, system scope returned 3 flavors and 403 for `GET /v2/images`.
  The controller SSH session was read-only and no provider resource changed.

## Security/review status

Initial independent review found tenant-scope and metadata/action issues. The
implementation was remediated with project-scoped list/detail predicates,
bounded secret-key filtering, empty admin provider metadata, normalized
allow-listed filters, and fail-closed action state rules. The fresh direct-host
probe additionally confirmed that the lab Glance policy rejects system-scoped
image listing with 403 while the project-scoped connection succeeds. The task
is therefore deferred rather than marked Done pending TMS integration, a
scope-policy decision, and final re-review.

## Limitations/follow-up

- Resolve the remaining independent-review findings before marking
  CPS/OPS-1906 Done. The live CPS/OpenStack comparison is recorded with fresh
  direct-host probe evidence and provider request evidence.
- Implementation commits are task-scoped, but acceptance remains deferred;
  CPS commit is `0a68e15` and OPS commit is `bc106c2`; pushed refs are
  intentionally absent.
