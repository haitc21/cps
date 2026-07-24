# Sprint 10 — OpenStack tenant binding and ownership

**Status:** Proposed  
**Dates:** 2026-08-08 to 2026-08-21  
**Capacity:** 21 combined points  
**Sprint Goal:** CMP can explicitly ask CPS to create OpenStack domain/project
bindings by `org_id` and `workspace_id` without using provider inventory as
the source of truth.

**Canonical design:**
`../../docs/superpowers/specs/2026-07-24-openstack-cmp-org-workspace-binding-spec.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-704 CMP-owned domain/project binding APIs | 13 | CPS | OPS-704 | Ready |

## Delivery tasks

- [ ] Confirm contract/schema readiness for domain and project binding rows.
- [ ] Add failing acceptance and unit tests for explicit binding creation.
- [ ] Implement the smallest CPS vertical slice for domain/project binding.
- [ ] Add migration and repository coverage for `org_id` and `workspace_id`.
- [ ] Verify inventory cannot auto-adopt an unbound provider object.
- [ ] Update API and operational documentation for the new binding workflow.
- [ ] Run the Definition of Done quality gates.

## Acceptance

- `POST` create-domain requires `org_id` and persists it on the CPS binding row.
- `POST` create-project requires `org_id` and `workspace_id` and persists both.
- Project creation fails if the matching domain binding does not exist.
- Create is idempotent on the natural key and fails closed on name-only collision.
- Inventory refresh remains read-only and cannot create or reassign bindings.
- The schema keeps `provider_type` and `binding_kind` explicit so VMware can
  add different binding kinds later without replacing the model.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Existing inventory tables may tempt ownership inference by name | CPS | Keep binding rows separate from inventory rows and enforce natural keys | Open |
| Project create depends on an existing domain binding | CPS | Validate dependency before enqueueing the create operation | Open |
| Later VMware support could pressure the model toward OpenStack-specific fields | CPS | Keep `provider_type` and `binding_kind` explicit and generic | Open |

## Review evidence

- Demo scenario:
- Test/migration commands and results:
- Contract checksum:
- Known limitations:

## Retrospective actions

- Keep: explicit natural-key ownership binding.
- Improve: clearer error mapping for provider-side name collisions.
- One measurable action for next sprint: add a binding lookup test that proves
  inventory-only data cannot create a row.
