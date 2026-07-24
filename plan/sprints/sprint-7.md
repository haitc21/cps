# Sprint 7 — Scoped connection and identity inventory foundation

**Status:** Proposed — not started  
**Dates:** 2026-07-27 to 2026-08-07  
**Capacity:** Confirm at Sprint Planning; proposed 50 combined points  
**Sprint Goal:** Validate administrative OpenStack connection scope and
convergently inventory domains and projects through pinned CPS/OPS contracts,
without enabling identity mutations.

**Canonical design:**  
`docs/superpowers/specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`

**Canonical implementation plan:**  
`docs/superpowers/plans/2026-07-24-openstack-resource-control-plane-expansion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-701 Resource-operation and scope contracts | 8 | CPS | OPS-701 | Proposed |
| CPS-702 Scoped provider-connection migration/API | 8 | CPS | OPS-702 validation result | Proposed |
| CPS-703 Domain/project inventory persistence and query | 13 | CPS | OPS-703 | Proposed |
| OPS-701 Pin and validate scope/identity contracts | 5 | OPS | CPS-701 canonical artifacts | Proposed |
| OPS-702 Effective scope discovery | 8 | OPS | CPS-702 contract | Proposed |
| OPS-703 Domain/project collectors and mappers | 8 | OPS | CPS-703 inventory contract | Proposed |

Planning rule: if confirmed capacity is below 50 points, retain CPS-701,
CPS-702, OPS-701, and OPS-702 as the minimum vertical slice; return CPS-703 and
OPS-703 to Ready rather than partially implementing them.

## Delivery tasks

- [ ] Approve the design delta and administrative test-resource policy.
- [ ] Confirm contract/schema readiness and story acceptance examples.
- [ ] Add failing scope, contract, migration, collector, and reconciliation tests.
- [ ] Implement canonical CPS scope/domain/project contracts.
- [ ] Pin and validate exact CPS contract artifacts in OPS.
- [ ] Migrate existing connections to explicit `PROJECT` scope.
- [ ] Discover effective OpenStack token scope without exposing token/catalog.
- [ ] Add typed domain persistence and canonical domain/project ownership.
- [ ] Collect domains/projects with pagination and missing-field tolerance.
- [ ] Verify cross-connection deduplication and safe full-sync finalization.
- [ ] Add mocked RabbitMQ integration and read-only real-cloud acceptance.
- [ ] Verify redaction, capability reasons, provider request IDs, and failures.
- [ ] Update API, migration, compatibility, and operational documentation.
- [ ] Run the Definition of Done quality gates.

## Story acceptance

### CPS-701

- Scope kind, owner reference, normalized identity resource, tombstone, and
  operation result models validate in Pydantic and JSON Schema.
- Golden fixtures cover supported, unsupported, replay, and already-absent
  results without secrets.
- Existing instance contracts remain compatible.
- Checksum manifest is deterministic and ready for OPS pinning.

### CPS-702

- `scope_kind` supports `SYSTEM`, `DOMAIN`, and `PROJECT`.
- Existing rows migrate to `PROJECT` without credential or project loss.
- Clean install, current-head upgrade, and downgrade tests pass.
- Scope fields become immutable after successful validation.
- Administrative operations can require scope without trusting a user-supplied
  role/name.

### CPS-703

- Identity domains are typed inventory with provider-level stable identity.
- Projects retain explicit owner-domain identity.
- Same domain/project visible through multiple connections is not duplicated by
  name or accidentally deleted.
- List/get filters include provider, connection visibility, owner domain, and
  lifecycle state.
- Partial or failed identity collection never marks missing rows deleted.

### OPS-701

- Pinned schemas, fixtures, and checksum match CPS byte-for-byte.
- Unsupported major versions reject before provider access.
- SDK objects cannot serialize into identity events.

### OPS-702

- Effective system/domain/project scope is discovered through supported SDK
  behavior.
- Project credentials do not report administrative identity capabilities.
- Clouds without system scope report explicit safe reasons.
- Raw token, service catalog, password, and authorization headers never leave
  the connection boundary.

### OPS-703

- Domain and project collectors use pagination and tolerate optional fields.
- Mappers emit only canonical primitives and provider IDs.
- Unsupported/forbidden domain listing is explicit and does not fail unrelated
  project collection.
- Targeted NotFound produces a tombstone; timeout/401/403 never implies delete.
- Replay publishes equivalent IDs and checksums.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Sprint 6 remains open | Product Owner | Start Sprint 7 only after Sprint 6 closure or explicit reprioritization | Open |
| Proposed 50 points exceeds capacity | Scrum Team | Apply documented minimum-slice rule at Planning | Open |
| Administrative credential unavailable | Product Owner | Approve read-only system/domain credential before Sprint Planning | Open |
| Cross-connection duplicate identity | CPS | Decide canonical provider identity before migration implementation | Open |
| Provider lacks system scope | OPS | Exercise domain/admin and project variants; report capability reason | Open |
| Existing dirty implementation work overlaps contracts | CPS/OPS | Preserve changes and rebase plan work only after owner review | Open |

## Review evidence

- Demo scenario: validate an administrative connection, run identity inventory,
  and query one domain with its projects from CPS.
- Test/migration commands and results:
- Contract checksum:
- OPS pinned checksum:
- Real-cloud scope/capability result:
- Disposable resources: none; Sprint 7 is read-only.
- Known limitations:

## Retrospective actions

- Keep:
- Improve:
- One measurable action for next sprint:

