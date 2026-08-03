# CPS-1905 — Image/flavor cross-service acceptance

**Status:** Blocked — live release matrix incomplete
**Points:** 3  
**Paired task:** OPS-1905  
**Depends on:** CPS-1901..1904

## Outcome

The Sprint 19 image/flavor increment has reproducible automated and real-cloud
evidence, complete cleanup, aligned contracts, and operator-ready runbooks.

## Acceptance matrix

- List/detail/filter/pagination and curated-versus-admin authorization.
- Flavor create, access add/remove, extra-spec set/unset, safe delete.
- Image import, metadata/visibility/protection, member grant/revoke,
  deactivate/reactivate, safe delete.
- Instance snapshot, launch/rebuild/resize/volume-from-image compatibility.
- Duplicate/redelivery; CPS/OPS restart; publish failure; late result; stale
  inventory; 401/403/404/409/429/5xx; timeout; unsupported capability.
- Negative security cases: image bytes, embedded/signed credentials, secret
  metadata, cross-provider/project reference, non-admin catalog mutation.
- Zero-residual cleanup verified by CPS reconciliation and OpenStack CLI.

## AI/Superpowers workflow

**Mandatory skill chain:** `superpowers:using-superpowers` →
`superpowers:writing-plans` → `codex-security:threat-model` →
`superpowers:using-git-worktrees` →
`superpowers:subagent-driven-development` or `superpowers:executing-plans` →
`superpowers:test-driven-development` for any acceptance-code change →
`superpowers:requesting-code-review` / `superpowers:receiving-code-review` →
`codex-security:security-diff-scan` →
`superpowers:verification-before-completion` → live curl/CLI/runbook →
`superpowers:finishing-a-development-branch`. The final security scan report,
finding ledger, and closure of every Critical/High finding are release evidence.

1. **Planner — Codex ChatGPT 5.6 sol:** inventory all Sprint 19 acceptance
   criteria and task evidence, identify missing branches, produce a deterministic
   scenario order, unique resource naming, cleanup ledger, failure injection,
   exact curl/CLI assertions, and release commit plan.
2. **Worker — Cursor Composer 2.5 Fast:** implement only missing acceptance test/
   script/runbook gaps; run contract checksum, migration, unit/integration/E2E,
   restart/replay, and real-cloud scenarios; capture redacted evidence.
3. **Reviewer — Codex ChatGPT 5.6 luna:** independently reconcile criteria to
   evidence, audit scripts for destructive scope/secrets, confirm every CPS API
   success has CLI proof, verify cleanup, checksums, migration, and known limits.
4. Worker fixes evidence/code gaps and reruns affected scenarios; Reviewer
   performs final release review. No waived critical/high finding.

## Required live procedure

For each mutation, the runbook must record: CPS `curl` request (secret fields
redacted), HTTP/correlation/operation IDs, terminal operation, CPS resource
detail, matching OpenStack CLI command/output summary, material-field comparison,
cleanup command, CLI not-found/list absence, and post-cleanup CPS refresh. A
single broad E2E call does not replace per-task verification.

## Quality and Git gates

- CPS and OPS checksums identical; OpenAPI/JSON Schema/golden fixtures pass.
- Ruff, MyPy, full tests, migration lifecycle, Compose health, diff check, and
  secret scan pass in both repositories.
- Consolidate links in `docs/runbooks/sprint-19-image-flavor-release.md` and
  update both sprint review-evidence sections.
- After explicit Git authorization, commit/push CPS-1905 and OPS-1905 as
  separate task-scoped commits. Record hashes, remote refs, and clean worktrees.

## Done when

All criteria map to fresh evidence, all disposable resources are absent,
runbooks are reproducible, no high finding remains, and both commits are pushed.
