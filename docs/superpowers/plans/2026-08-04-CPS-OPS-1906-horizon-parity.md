# CPS/OPS-1906 Horizon parity micro-plan

**Status:** Deferred after implementation evidence; TMS integration and OpenStack scope-policy closure remain follow-up work.

## Story and outcome

- Story IDs: CPS-1906 and paired OPS-1906.
- Outcome: authorized consumers can list and inspect approved image/flavor catalog
  entries with stable filtering, sorting, pagination, capability/action metadata,
  and safe provider-neutral fields.
- In scope: additive read-only contract/API and provider inventory semantics.
- Out of scope: image bytes/URL import, flavor replacement, new mutations,
  Django/Horizon runtime dependencies, and changes to TMS/LMS.

## Acceptance and contract decision

- Preserve the existing response envelope and `schema_version`; all new fields
  are optional/additive. Unknown major versions remain rejected by existing
  validators.
- Admin responses retain safe inventory projections; member responses remain
  curated and never expose provider attributes, credentials, signed URLs, image
  bytes, or raw provider bodies.
- Filters are allow-listed and normalized (`name`, provider status, visibility,
  public/protected/enabled, approval, owner/project); sort is allow-listed with
  deterministic ID tie-breaker.

## Exact files/interfaces and blast radius

- CPS: `src/cps/api/schemas/catalog.py`, `src/cps/api/routers/catalog.py`,
  `src/cps/infrastructure/db/repositories/inventory.py`,
  `tests/unit/api/test_catalog.py`, `tests/contract/test_catalog_contract.py`,
  `docs/runbooks/sprint-19-portal-parity.md`, and Sprint 19 evidence.
- OPS: `src/ops/openstack/inventory.py`,
  `tests/unit/openstack/test_inventory.py`, pinned contract fixtures/checksums
  only if the CPS additive response requires them.
- CodeGraph was queried before exact-text discovery; indexed results were noisy
  and did not expose the CPS/OPS symbols, so exact `rg` was used for the listed
  Python/config/test surfaces. Re-check callers with focused tests after edits.

## RED-GREEN-REFACTOR

- [x] RED CPS: filter/sort/detail/action-capability and member-scope tests fail
  for the expected missing fields/arguments.
- [x] RED OPS: image/flavor tag/status/visibility/access and bounded enrichment
  tests fail for the expected missing normalized fields/behavior.
- [x] Record observed RED output before production edits.
- [x] GREEN: implement the smallest additive CPS contract/repository/API slice.
- [x] GREEN: implement the smallest OPS mapper/collector/discovery slice.
- [x] REFACTOR only with focused suites green; preserve provider-neutral boundary.

## Failure, security, and operational matrix

- Test invalid filters, unsupported sort, empty/missing fields, 401/403/404,
  duplicate/read replay, provider 429/5xx, missing SDK methods, and bounded
  enrichment. No provider mutation is allowed in this task.
- Verify no secret-like keys, signed URLs, image bytes, authorization data, or
  raw provider exception/body appear in responses/logs/fixtures.
- Live verification is read-only: CPS API list/detail/capabilities as admin and
  member, compare IDs/material fields with `openstack flavor list/show` and
  `openstack image list/show`, then verify no provider resource count changed.

## Commands and evidence

- CPS focused: `rtk pytest -q tests/unit/api/test_catalog.py tests/contract/test_catalog_contract.py`.
- OPS focused: `rtk pytest -q tests/unit/openstack/test_inventory.py` plus contract pin checks.
- Affected/full: repository formatter, lint, typing, contract checks, full tests,
  `rtk git diff --check`, and secret scan.
- Runtime: start CPS/OPS directly on host; containers are limited to DB,
  RabbitMQ, and Keycloak. Use `curl` and `openstack` CLI for live read-only checks.
- [ ] Write redacted `docs/runbooks/sprint-19-portal-parity.md` with commands,
  outputs, provider IDs/material comparisons, review/security findings,
  cleanup ledger (read-only/no resources), limitations, and commit hashes.
- [x] Update task/sprint statuses with the deferred/blocked acceptance limitation; do not mark Done.

## Review and commit boundaries

- [x] Independent specification/contract and code-quality/security review; initial
  review findings were remediated and re-review remains open.
- [x] Validate every finding technically and rerun affected tests.
- [ ] Proposed commits: `feat(catalog): define Horizon-parity consumer contracts`
  in CPS, then `feat(inventory): expose Horizon-parity catalog semantics` in OPS.
- [ ] Push only the task-scoped commits after all gates pass; never stage or
  commit unrelated user changes.
