# Sprint 10 — OpenStack tenant binding and ownership

**Status:** Complete — implementation, live acceptance, and cleanup verified
**Dates:** 2026-08-08 to 2026-08-21  
**Capacity:** 21 combined points  
**Sprint Goal:** CMP can explicitly ask CPS to create OpenStack domain/project
bindings by `provider_id`, `org_id`, and `workspace_id` without using provider
inventory as the source of truth.

**Canonical design:**
`../../docs/superpowers/specs/2026-07-24-openstack-cmp-org-workspace-binding-spec.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-704 CMP-owned domain/project binding APIs | 13 | CPS | OPS-704 | Done |

## Delivery tasks

- [x] Confirm contract/schema readiness for domain and project binding rows keyed
  by `provider_id`.
- [x] Add failing acceptance and unit tests for explicit binding creation under
  `/api/v1/providers/{provider_id}/...`.
- [x] Implement the smallest CPS vertical slice for domain/project binding.
- [x] Add migration and repository coverage for `org_id` and `workspace_id`.
- [x] Verify inventory cannot auto-adopt an unbound provider object.
- [x] Update API and operational documentation for the new binding workflow.
- [x] Run the Definition of Done quality gates.

## Acceptance

- `POST /api/v1/providers/{provider_id}/identity-domains` requires `org_id` and
  persists it on the CPS binding row with the same `provider_id`.
- `POST /api/v1/providers/{provider_id}/identity-projects` requires `org_id`
  and `workspace_id` and persists both with the same `provider_id`.
- Project creation fails if the matching domain binding does not exist for the
  same `provider_id`.
- Create is idempotent on `(provider_id, org_id)` or
  `(provider_id, org_id, workspace_id)` and fails closed on name-only collision.
- Inventory refresh remains read-only and cannot create or reassign bindings.
- The schema keeps `provider_type` and `binding_kind` explicit so VMware can
  add different binding kinds later without replacing the model.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Existing inventory tables may tempt ownership inference by name | CPS | Keep binding rows separate from inventory rows and enforce `(provider_id, org_id)` natural keys | Open |
| Project create depends on an existing domain binding | CPS | Validate dependency on the same `provider_id` before enqueueing the create operation | Open |
| Later VMware support could pressure the model toward OpenStack-specific fields | CPS | Keep `provider_type` and `binding_kind` explicit and generic | Open |

## Review evidence

- Demo scenario: provider onboarding and validation succeeded against the live
  OpenStack controller; CPS created and cleaned up explicit domain/project
  bindings keyed by provider, organization, and workspace.
- Test/migration commands and results: CPS full suite, Ruff, mypy, Alembic
  check, Compose health, contract checks, and provider validation passed.
- Contract checksum: CPS and OPS credential-scope contracts are synchronized and
  validated; identity command delivery keys are allowlisted on both services.
- Live evidence: domain create/update-disable/delete and project create/delete
  reached `SUCCEEDED`; provider resources were absent after cleanup.

## Retrospective actions

- Keep: explicit natural-key ownership binding.
- Improve: clearer error mapping for provider-side name collisions.
- One measurable action for next sprint: retain the binding lookup test and add
  deployment-level role/quota acceptance when policy permits it.
