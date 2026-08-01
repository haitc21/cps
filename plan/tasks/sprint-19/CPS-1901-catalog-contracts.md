# CPS-1901 — Catalog detail and compatibility contracts

**Status:** Implemented and reviewed — paired OPS-1901 live acceptance pending  
**Points:** 5  
**Paired task:** OPS-1901  
**Depends on:** CPS-1703

## Outcome

CPS exposes provider-neutral, paginated image/flavor list and detail views with
the fields needed by Horizon-equivalent administration and by safe instance
source/size validation.

## Deliverables

- Extend canonical inventory/catalog schemas for flavor extra specs/access and
  image owner, status, protection, container/disk format, virtual size, tags,
  properties, checksum, minimum disk/RAM, and visibility.
- Add list/detail filters: name, status, visibility/public, owner/project,
  disk format, minimum/maximum size, minimum disk/RAM, and catalog approval.
- Preserve user read-only curated catalog endpoints; introduce a separate
  administrator authorization dependency for full inventory details.
- Add compatibility result used by launch/rebuild/resize/volume-from-image:
  approved/live status, flavor RAM/root disk versus image minima, launchable
  format, provider/project scope, and reason codes.
- Add migration only if typed columns are justified; otherwise preserve bounded
  provider attributes and index only fields required for query performance.

## Tests first

- Contract fixtures for full/minimal image and flavor, additive fields, unknown
  major version, invalid status/visibility/negative sizes, and secret keys.
- API tests for every filter, pagination, detail 404, user/admin separation,
  stale/soft-deleted rows, and compatibility failure reasons.
- Repository tests for stable ordering and query/index behavior.

## AI/Superpowers workflow

**Mandatory skill chain:** `superpowers:using-superpowers` →
`superpowers:writing-plans` →
`superpowers:using-git-worktrees` →
`superpowers:subagent-driven-development` or `superpowers:executing-plans` →
`superpowers:test-driven-development` →
`superpowers:requesting-code-review` / `superpowers:receiving-code-review` →
`superpowers:verification-before-completion` → live curl/CLI/runbook →
`superpowers:finishing-a-development-branch`. Use
`superpowers:brainstorming` before writing the plan if a design choice remains.
Review findings must be triaged and valid findings fixed; the final task diff
must pass the repository secret scan before completion.

1. **Planner — Codex ChatGPT 5.6 sol:** read `AGENTS.md`, canonical designs,
   Sprint 19, CodeGraph callers of catalog schemas/repository, Horizon
   `api/glance.py`, `api/nova.py`, and image/flavor tables. Produce field map,
   compatibility/version decision, failing-test sequence, migration choice,
   curl/CLI script, and commit plan.
2. **Worker — Cursor Composer 2.5 Fast:** add failing contract/API/repository
   tests; update canonical CPS schema/fixtures/checksum; implement the smallest
   query/detail/compatibility slice; refactor only after green.
3. **Reviewer — Codex ChatGPT 5.6 luna:** check provider neutrality, data
   bounds/redaction, authorization separation, pagination, compatibility math,
   migration/index safety, OpenAPI, and OPS pin impact. Return findings by
   severity with file/line evidence.
4. Worker resolves findings and reruns tests; Reviewer re-approves the final
   diff. Update OPS pinned artifacts only through paired OPS-1901.

## Verification, runbook, and Git gate

1. Run contract, API, repository, migration (if applicable), Ruff, MyPy, full
   CPS tests, `rtk git diff --check`, and secret scan.
2. Run `curl` for image/flavor list and detail against CPS, recording request,
   status, correlation ID, pagination, and redacted body.
3. Run `openstack image list/show` and `openstack flavor list/show`; compare
   provider IDs and all mapped fields with CPS. Trigger targeted refresh first
   if inventory is stale and compare again.
4. Write `docs/runbooks/sprint-19-catalog-contracts.md`, including environment,
   commands, comparison table, limitations, and cleanup (read-only: none).
5. After explicit Git authorization, commit only CPS-1901 changes and push the
   task branch. Record branch, commit hash, remote ref, and clean status.

## Done when

Contracts are pinned-ready, query/detail and compatibility tests pass, live CPS
and CLI results match, runbook evidence exists, and the task commit is pushed.
