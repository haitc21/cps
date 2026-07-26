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

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1201](../tasks/sprint-13/CPS-1201-provider-owned-credential.md) | Provider-owned encrypted credential, migration, API and contract cleanup | None | Ready |
| [CPS-1202](../tasks/sprint-13/CPS-1202-canonical-project-ownership.md) | Canonical project plus project FK on tenant resources | CPS-1201, CPS-704 | Ready |
| [CPS-1203](../tasks/sprint-13/CPS-1203-resource-authorization-boundary.md) | Ownership resolver and fail-closed TMS authorization port/stub | CPS-1202 | Ready with external dependency |

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
