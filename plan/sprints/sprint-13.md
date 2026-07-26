# Sprint 13 — Provider credential, tenant ownership, and authorization boundary

**Status:** Ready for implementation  
**Dates:** 2026-09-19 to 2026-10-02  
**Capacity:** 39 CPS points  
**Sprint Goal:** CPS owns one encrypted credential per provider, links every
tenant resource to a canonical organization/workspace project, and fails closed
unless the user action receives an authorization decision through the TMS client
boundary.

**Canonical design:**  
`../../docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`

**Repository constraint:** Only CPS and the paired OPS contract may change.
TMS/LMS changes are forbidden. BMS is unaffected by this sprint.

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1201 Provider-owned encrypted credential | 13 | CPS | OPS-1201 | Ready |
| CPS-1202 Canonical project ownership for tenant resources | 13 | CPS | OPS-1201 | Ready |
| CPS-1203 Fail-closed resource authorization boundary | 13 | CPS | OPS-1202 | Ready |

## Delivery tasks

### CPS-1201 — Provider-owned encrypted credential

- [ ] Add failing migration/model tests for provider-owned encrypted fields and removal of `provider_connections.credential_id`.
- [ ] Add an ambiguity guard for a legacy provider referencing multiple credentials; verify the current empty database upgrade.
- [ ] Move AES-GCM AAD from credential ID to provider ID without exposing plaintext during migration or rotation.
- [ ] Refactor provider aggregate/repository/create/update/list/get paths.
- [ ] Remove credential schemas, router, service, errors, repository methods, and public OpenAPI paths.
- [ ] Resolve secrets using only `provider_connection_id`; invalidate all provider connections after credential rotation.
- [ ] Remove `credential_reference` from operation and CPS/OPS fixtures.
- [ ] Add redaction, key-unavailable, rotation, optimistic-lock, and multi-scope connection tests.

### CPS-1202 — Canonical project ownership

- [ ] Add `provider_id`, `org_id`, `workspace_id`, and `ownership_state` to the canonical project model with provider-level uniqueness constraints.
- [ ] Add `project_id` and `project_provider_resource_id` to every tenant-owned inventory table and the required indexes.
- [ ] Normalize project identity from OpenStack payloads and explicitly define the project-scoped fallback.
- [ ] Resolve project foreign keys during operation result persistence, full inventory, and targeted refresh.
- [ ] Preserve organization/workspace ownership during inventory upsert and tombstone processing.
- [ ] Project a `READY` identity binding into the canonical project row.
- [ ] Add an ownership reconciler for provider resources observed before their project mapping.
- [ ] Add tenant-safe list/get filters and cross-provider/cross-workspace tests.

### CPS-1203 — Authorization boundary

- [ ] Define permission constants, `AuthorizationDecision`, outbound port, and stable deny/unavailable errors.
- [ ] Implement a strict HTTP TMS adapter without changing TMS and a deterministic configurable stub for local/CI tests.
- [ ] Add a resource ownership resolver that loads resource plus canonical project with an indexed query.
- [ ] Enforce authorization before reads, operation persistence, outbox writes, or provider mutation for every tenant resource API.
- [ ] Authorize list once per workspace and bulk operations once per distinct workspace.
- [ ] Store only safe decision metadata in `operations.actor_context`; never persist JWTs or role lists.
- [ ] Reauthorize expired queued decisions before dispatch or fail closed.
- [ ] Cover explicit deny, timeout, malformed response, unbound ownership, disabled workspace mapping, and cross-tenant non-disclosure.
- [ ] Document production configuration as blocked until the external TMS endpoint exists; verify disabled/missing configuration fails closed.

## Acceptance

- One provider has exactly one encrypted OpenStack credential and any number of scoped connections.
- Credential plaintext and bearer tokens are absent from DB projections, logs, messages, fixtures, and errors.
- Tenant-owned resource rows resolve to one canonical CPS project and therefore one `org_id`/`workspace_id`.
- User-provided ownership cannot override persisted ownership for an existing resource.
- No tenant read or mutation proceeds without an allow decision.
- TMS outage or missing production endpoint creates no operation and publishes no command.
- TMS and LMS repositories remain byte-for-byte untouched by this sprint.
- CPS format, lint, typing, unit, integration, contract, migration lifecycle, secret scan, and Compose smoke gates pass.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| TMS has no internal authorization endpoint in the allowed scope | External/TMS | Keep a strict CPS outbound port, use stub only for test/local, fail closed in production | Open |
| Inventory may observe resource before project | CPS | Persist provider project ID, mark unresolved, reconcile later, deny tenant access meanwhile | Open |
| Shared/public resources have no tenant owner | CPS | Keep project FK nullable and apply explicit global-resource policy | Open |
| Credential migration could encounter legacy one-to-many data | CPS | Detect ambiguity and abort migration instead of selecting a credential silently | Open |

## Review evidence

- Migration upgrade/downgrade:
- Provider credential redaction/rotation:
- Ownership reconciliation and cross-workspace isolation:
- Authorization allow/deny/unavailable/expiry:
- CPS/OPS contract checksum:
- Verification that TMS/LMS have no diff:

## Retrospective actions

- Keep:
- Improve:
- One measurable action for the next sprint:
