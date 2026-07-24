# Sprint 7 — Scoped connection and identity inventory foundation

**Status:** Complete (implementation and review finished 2026-07-24)  
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
| CPS-701 Resource-operation and scope contracts | 8 | CPS | OPS-701 | Done |
| CPS-702 Scoped provider-connection migration/API | 8 | CPS | OPS-702 validation result | Done |
| CPS-703 Domain/project inventory persistence and query | 13 | CPS | OPS-703 | Done |
| OPS-701 Pin and validate scope/identity contracts | 5 | OPS | CPS-701 canonical artifacts | Done |
| OPS-702 Effective scope discovery | 8 | OPS | CPS-702 contract | Done |
| OPS-703 Domain/project collectors and mappers | 8 | OPS | CPS-703 inventory contract | Done |

Planning rule: if confirmed capacity is below 50 points, retain CPS-701,
CPS-702, OPS-701, and OPS-702 as the minimum vertical slice; return CPS-703 and
OPS-703 to Ready rather than partially implementing them.

## Delivery tasks

- [x] Approve the design delta and administrative test-resource policy.
- [x] Confirm contract/schema readiness and story acceptance examples.
- [x] Add failing scope, contract, migration, collector, and reconciliation tests.
- [x] Implement canonical CPS scope/domain/project contracts.
- [x] Pin and validate exact CPS contract artifacts in OPS.
- [x] Migrate existing connections to explicit `PROJECT` scope.
- [x] Discover effective OpenStack token scope without exposing token/catalog.
- [x] Add typed domain persistence and canonical domain/project ownership.
- [x] Collect domains/projects with pagination and missing-field tolerance.
- [x] Verify cross-connection deduplication and safe full-sync finalization.
- [x] Add mocked RabbitMQ integration and read-only real-cloud acceptance.
- [x] Verify redaction, capability reasons, provider request IDs, and failures.
- [x] Update API, migration, compatibility, and operational documentation.
- [x] Run the Definition of Done quality gates.

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
| Sprint 6 remains open | Product Owner | Explicitly reprioritized for this implementation pass | Resolved |
| Proposed 50 points exceeds capacity | Scrum Team | All selected stories implemented and tested | Resolved |
| Administrative credential unavailable | Product Owner | Project-scope real-cloud validation completed; admin capability remains explicit/negative | Accepted |
| Cross-connection duplicate identity | CPS | Provider resource IDs and canonical ownership reconciliation implemented | Resolved |
| Provider lacks system scope | OPS | Capability reasons are reported without inferring admin role | Accepted |
| Existing dirty implementation work overlaps contracts | CPS/OPS | Preserved and verified independently | Resolved |

## Review evidence

- Demo scenario: validate an administrative connection, run identity inventory,
  and query one domain with its projects from CPS.
- Test/migration commands and results: CPS `485 passed, 193 skipped`; OPS `352 passed, 24 skipped`; CPS DB integration `146 passed`; Alembic upgrade to `20260724_0006` passed.
- Contract checksum: CPS semantic validator passed (`15 files`).
- OPS pinned checksum: byte-identical to CPS manifest and fixtures.
- Real-cloud scope/capability result: validation succeeded; effective `PROJECT` scope and safe `SYSTEM_SCOPE_REQUIRED` reasons returned for domain administration.
- Disposable resources: none; Sprint 7 is read-only.
- Known limitations: the dev OpenStack catalog advertises `controller` endpoints that refuse connections from the Compose network, so live domain/project inventory collection is environment-blocked; collector, pagination, forbidden-scope, reconciliation, and replay behavior are covered by tests.

## Retrospective actions

- Keep: canonical CPS-owned contract artifacts and explicit capability reasons.
- Improve: ensure provider catalog endpoints are routable from runtime networks before live inventory acceptance.
- One measurable action for next sprint: add a deployment preflight that checks every advertised OpenStack endpoint from CPS/OPS containers.
