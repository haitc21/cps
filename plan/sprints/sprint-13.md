# Sprint 13 — Provider credential, tenant ownership, and authorization boundary

**Status:** Done — CPS-1201/1202/1203/1204 complete for approved CPS/OPS scope
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
| CPS-1201 Provider-owned encrypted credential | 13 | CPS | OPS-1201 | Done |
| CPS-1202 Canonical project ownership for tenant resources | 13 | CPS | OPS-1201 | Done |
| CPS-1203 Fail-closed resource authorization boundary | 13 | CPS | OPS-1202 | Done — ingress TMS scope authorization |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1201](../tasks/sprint-13/CPS-1201-provider-owned-credential.md) | Provider-owned encrypted credential, migration, API and contract cleanup | None | Done — Active backlog: no |
| [CPS-1202](../tasks/sprint-13/CPS-1202-canonical-project-ownership.md) | Canonical project plus project FK on tenant resources | CPS-1201, CPS-704 | Done — Active backlog: no |
| [CPS-1203](../tasks/sprint-13/CPS-1203-resource-authorization-boundary.md) | Ingress fail-closed TMS organization/workspace scope authorization | CPS-1202 | Done — Active backlog: no |
| [CPS-1204](../tasks/sprint-13/CPS-1204-provider-creator-role.md) | Automatically grant the provider creator's highest admin role on created domain/project scopes | CPS-1201, OPS-1203 | Done — Active backlog: no |

## Execution sequence

1. Complete CPS-1201 and publish canonical schema/fixture changes.
2. Complete CPS-1202 with OPS owner normalization in parallel after contract
   readiness.
3. Complete CPS-1203 ingress TMS scope authorization against deployed TMS role-read APIs.
4. Integrate OPS-1202 safe decision context (follow-up — not part of CPS-1203 ingress slice).
5. Run joint contract, migration, cross-tenant, redaction, and Compose gates.
6. Verify `bms`, `tms`, and `lms` contain no sprint diff.

## Acceptance

- One provider has exactly one encrypted OpenStack credential and any number of scoped connections.
- Credential plaintext and bearer tokens are absent from DB projections, logs, messages, fixtures, and errors.
- Tenant-owned resource rows resolve to one canonical CPS project and therefore one `org_id`/`workspace_id`.
- User-provided ownership cannot override persisted ownership for an existing resource.
- Protected member API requests fail closed at ingress unless TMS organization/workspace
  membership allows the caller's verified subject for the supplied scope headers.
- TMS outage or malformed role-read response returns `503` at ingress without
  reaching a handler or creating durable side effects.
- TMS and LMS repositories remain byte-for-byte untouched by this sprint.
- CPS format, lint, typing, unit, integration, contract, migration lifecycle, secret scan, and Compose smoke gates pass.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| TMS has no internal authorization endpoint in the allowed scope | External/TMS | Integrate existing TMS organization/workspace role-read APIs for ingress scope checks; resource-level decision port remains follow-up | Resolved for ingress slice |
| Inventory may observe resource before project | CPS | Persist provider project ID, mark unresolved, reconcile later, deny tenant access meanwhile | Resolved |
| Shared/public resources have no tenant owner | CPS | Keep project FK nullable and apply explicit global-resource policy | Resolved |
| Credential migration could encounter legacy one-to-many data | CPS | Detect ambiguity and abort migration instead of selecting a credential silently | Resolved |

## Review evidence

- Migration lifecycle (disposable PostgreSQL 18): empty-to-head,
  downgrade-to-base, and re-upgrade-to-head pass (`6 passed`); the complete DB
  integration suite passes (`131 passed`).
- Provider credential rotation: `PATCH /api/v1/providers/019fa1a6-d0fe-7b64-8e1a-b4508587be86` `expected_version=3` → version 4, no password in response; fix double-increment in `ProviderService.update`.
- Inventory sync: `POST .../inventory-syncs` operation `019fa6ca-7d3f-7039-a82b-710488d713e0` SUCCEEDED after OPS collection-name normalization.
- Identity binding E2E: domain op `019fa6cc-d5dc-7420-a284-d23db3fe77e3`, project op `019fa6cc-e1f4-7d1d-8f5b-87e1a2cbddfc` SUCCEEDED; OpenStack project `7593702e28cd498c8e4648078130c1ad`; role assignment admin user `6d604e6297154229b98c5a5c6b357569`.
- Project ownership: `GET /api/v1/projects` shows `cmp180-s13-project` with `org_id=cmp-org-s13`, `workspace_id=cmp-ws-s13`, `ownership_state=MANAGED` after binding projection + inventory preserve (requires rebuilt `cps-worker`).
- Idempotency replay: identity-project duplicate `Idempotency-Key` returns same operation `019fa6d3-a5c5-77d7-822a-0bc6ea390e64`.
- CPS-1203 ingress TMS scope authorization: focused auth `33 passed`; affected
  integration `11 passed, 3 skipped`; full suite `671 passed, 182 skipped`; Ruff
  pass; mypy `137 files` pass; root and CPS-only compose config validation
  pass; live APP_OWNER bypass, exact role policy, member scope allow/deny, and
  TMS pause/unpause recovery pass. Luna final review approved with no findings
  (2026-08-04). User waived Codex Security diff scan for this completion.
  Persisted authorization decisions and queued-decision expiry remain
  unimplemented follow-up. CPS-1906 TMS dependency is closed by this slice; any
  separate OpenStack scope-policy work for CPS-1906 remains open.

## Retrospective actions

- Keep:
- Improve:
- One measurable action for the next sprint:
