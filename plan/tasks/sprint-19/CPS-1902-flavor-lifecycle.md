# CPS-1902 — Flavor lifecycle and project access

**Status:** Implemented and reviewed — paired OPS-1902 live acceptance pending
**Points:** 8
**Paired task:** OPS-1902
**Depends on:** CPS-1901

## Outcome

An authorized administrator can create/delete flavors and manage project
access and extra specs through durable, idempotent operations.

## Deliverables

- Admin APIs for create, delete, replace project access, and patch extra specs.
- Create fields aligned with Horizon: name, optional provider ID/`auto`, vCPUs,
  RAM MiB, root disk GiB, ephemeral GiB, swap MiB, and public/private access.
- Validate names/IDs, positive/bounded resources, duplicate name/ID, provider
  admin scope, capability, project references, and operation idempotency key.
- Keep core sizing immutable after create. Do not expose generic PATCH that
  deletes/recreates a flavor. Return a stable conflict/error explaining this.
- Persist operation/outbox atomically; refresh/persist normalized flavor and
  access after success; tombstone only after confirmed deletion.
- Prevent deletion when policy or dependency checks identify unsafe use unless
  an explicitly designed future force operation is approved.

## Tests first

- Contract/API tests for valid/invalid create, duplicate/reused idempotency key,
  admin denial, cross-provider project, core-field PATCH rejection, access and
  extra-spec add/update/remove.
- Unit/integration tests for outbox atomicity, duplicate result, late event,
  stale inventory, delete conflict, tombstone, and operation history.

## AI/Superpowers workflow

**Mandatory skill chain:** `superpowers:using-superpowers` →
`superpowers:writing-plans` → `codex-security:threat-model` →
`superpowers:using-git-worktrees` →
`superpowers:subagent-driven-development` or `superpowers:executing-plans` →
`superpowers:test-driven-development` →
`superpowers:requesting-code-review` / `superpowers:receiving-code-review` →
`codex-security:security-diff-scan` →
`superpowers:verification-before-completion` → live curl/CLI/runbook →
`superpowers:finishing-a-development-branch`. Invoke
`superpowers:brainstorming` if immutable sizing, delete safeguards, or access
semantics are not approved. Security findings at Critical/High block completion.

1. **Planner — Codex ChatGPT 5.6 sol:** map Horizon flavor form/API semantics to
   provider-neutral contracts, query CodeGraph operation/outbox consumers,
   define authorization and immutable-field rules, red tests, curl/CLI create-
   inspect-update-delete sequence, cleanup, and CPS/OPS commit boundaries.
2. **Worker — Cursor Composer 2.5 Fast:** write failing canonical contract and
   operation tests, update schemas/fixtures/checksum/OpenAPI, then implement API
   → application service → repository/outbox vertical slices one operation at a
   time. Never add OpenStackSDK to CPS.
3. **Reviewer — Codex ChatGPT 5.6 luna:** review scope/capability gates,
   idempotency fingerprints, race/duplicate behavior, project ownership,
   destructive-delete safeguards, error safety, audit history, and migration.
4. Worker fixes all findings and reruns focused/full gates; Reviewer rechecks.

## Verification, runbook, and Git gate

1. Run contract, API, application, DB/outbox, migration, Ruff, MyPy, full tests,
   diff check, and secret scan.
2. With a unique `cmp-s19-*` name, call CPS by `curl` to create flavor, poll
   operation, replace access, patch extra specs, and query detail.
3. Verify each step using `openstack flavor show`, `flavor access list`, and
   `flavor extra spec list`. Delete through CPS, poll success, then require
   `openstack flavor show` to return not found and CPS refresh to tombstone it.
4. Record commands, IDs, operation transitions, field comparisons, errors, and
   cleanup in `docs/runbooks/sprint-19-flavor-lifecycle.md`.
5. After explicit authorization, commit/push CPS-1902 separately; record CPS
   hash and paired OPS hash/ref in task evidence.

## Done when

Automated replay/failure tests and live CRUD/access/extra-spec verification pass,
cleanup is zero-residual, runbook exists, and both task commits are pushed.
