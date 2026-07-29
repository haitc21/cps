# Sprint 13 — Provider credential, tenant ownership, and authorization boundary

**Status:** Partial — 1201/1202/1204 evidence closed; 1203 deferred  
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
| CPS-1203 Fail-closed resource authorization boundary | 13 | CPS | OPS-1202 | Deferred — TMS endpoint out of scope |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1201](../tasks/sprint-13/CPS-1201-provider-owned-credential.md) | Provider-owned encrypted credential, migration, API and contract cleanup | None | Done — evidence in progress |
| [CPS-1202](../tasks/sprint-13/CPS-1202-canonical-project-ownership.md) | Canonical project plus project FK on tenant resources | CPS-1201, CPS-704 | Done — evidence in progress |
| [CPS-1203](../tasks/sprint-13/CPS-1203-resource-authorization-boundary.md) | Ownership resolver and fail-closed TMS authorization port/stub | CPS-1202 | Deferred |
| CPS-1204 | Automatically grant the provider creator's highest admin role on created domain/project scopes | CPS-1201, OPS-1203 | Done |

## Execution sequence

1. Complete CPS-1201 and publish canonical schema/fixture changes.
2. Complete CPS-1202 with OPS owner normalization in parallel after contract
   readiness.
3. Complete CPS-1203 against the deterministic CPS stub.
4. Integrate OPS-1202 safe decision context.
5. Run joint contract, migration, cross-tenant, redaction, and Compose gates.
6. Verify `bms`, `tms`, and `lms` contain no sprint diff.

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

- Migration upgrade (disposable `cps_test`): `CPS_RUN_INTEGRATION=1 CPS_TEST_DATABASE_URL=postgresql+psycopg://cmp:***@127.0.0.1:5432/cps_test uv run pytest tests/integration/db/test_migration_lifecycle.py` — upgrade/head OK; downgrade rehearsal fails at `20260726_0011` (`credentials` table) — tracked backlog.
- Provider credential rotation: `PATCH /api/v1/providers/019fa1a6-d0fe-7b64-8e1a-b4508587be86` `expected_version=3` → version 4, no password in response; fix double-increment in `ProviderService.update`.
- Inventory sync: `POST .../inventory-syncs` operation `019fa6ca-7d3f-7039-a82b-710488d713e0` SUCCEEDED after OPS collection-name normalization.
- Identity binding E2E: domain op `019fa6cc-d5dc-7420-a284-d23db3fe77e3`, project op `019fa6cc-e1f4-7d1d-8f5b-87e1a2cbddfc` SUCCEEDED; OpenStack project `7593702e28cd498c8e4648078130c1ad`; role assignment admin user `6d604e6297154229b98c5a5c6b357569`.
- Project ownership: `GET /api/v1/projects` shows `cmp180-s13-project` with `org_id=cmp-org-s13`, `workspace_id=cmp-ws-s13`, `ownership_state=MANAGED` after binding projection + inventory preserve (requires rebuilt `cps-worker`).
- Idempotency replay: identity-project duplicate `Idempotency-Key` returns same operation `019fa6d3-a5c5-77d7-822a-0bc6ea390e64`.
- CPS-1203: Deferred — no TMS auth port.

## Retrospective actions

- Keep:
- Improve:
- One measurable action for the next sprint:
