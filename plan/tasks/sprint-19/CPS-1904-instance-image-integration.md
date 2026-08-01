# CPS-1904 — Instance image snapshot and consumer integration

**Status:** Proposed  
**Points:** 5  
**Paired task:** OPS-1904  
**Depends on:** CPS-1901, CPS-1903, CPS-1701

## Outcome

Users can create an image snapshot from an owned instance, while all image and
flavor consumers apply consistent approval, status, scope, and size checks.

## Deliverables

- Durable instance-image-snapshot API with name, bounded metadata, idempotency,
  ownership, provider, instance-state, image-service capability, and quota
  validation.
- Snapshot result is normalized as image inventory with `image_type=snapshot`
  (or canonical equivalent), source instance ID, owner, status, and properties.
- Centralize compatibility checks used by instance create, rebuild, resize, and
  volume-from-image: image active/launchable/approved; flavor approved/live;
  flavor RAM/root disk satisfy image minima; references share provider/project.
- Preserve existing instances when approval is later removed; block only new
  operations. Return stable reason codes suitable for UI guidance.

## Tests first

- Contract/API tests for valid snapshot, invalid instance state/ownership/name,
  quota/capability failure, duplicate key, and no image bytes in payload.
- Consumer regression tests for every image/flavor compatibility branch,
  stale/tombstoned inventory, removed approval, and exact reason code.
- Recovery tests for queued snapshot, timeout, late completion, and duplicate.

## AI/Superpowers workflow

**Mandatory skill chain:** `superpowers:using-superpowers` →
`superpowers:writing-plans` → `codex-security:threat-model` →
`superpowers:using-git-worktrees` →
`superpowers:subagent-driven-development` or `superpowers:executing-plans` →
`superpowers:test-driven-development` →
`superpowers:requesting-code-review` / `superpowers:receiving-code-review` →
`codex-security:security-diff-scan` →
`superpowers:verification-before-completion` → live curl/CLI/runbook →
`superpowers:finishing-a-development-branch`. Use brainstorming if snapshot
ownership, quota, or compatibility policy is unresolved. Critical/High security
findings block completion.

1. **Planner — Codex ChatGPT 5.6 sol:** inspect existing create/rebuild/resize/
   volume paths and Horizon `snapshot_create`; use CodeGraph to locate all
   consumers; produce centralized rule table, contract plan, red tests, curl/
   CLI snapshot-and-consume scenario, cleanup, and commit boundaries.
2. **Worker — Cursor Composer 2.5 Fast:** write failing contracts/consumer/
   recovery tests, implement the snapshot vertical slice and shared compatibility
   service, then remove duplicated checks while tests stay green.
3. **Reviewer — Codex ChatGPT 5.6 luna:** verify every consumer is covered,
   ownership/quota/status rules, removed-approval behavior, idempotency and late
   results, no secret/binary data, and backward compatibility.
4. Worker fixes findings and reruns affected/full suites; Reviewer re-approves.

## Verification, runbook, and Git gate

Create a disposable ACTIVE instance from approved image/flavor through CPS.
Call snapshot by `curl`, poll success, and compare CPS image detail with
`openstack server image create` semantics and `openstack image show`. Use the
snapshot in a CPS launch or rebuild, verify the server with `openstack server
show`, then delete snapshot and disposable server through CPS and verify CLI
absence. Record all commands/results in
`docs/runbooks/sprint-19-instance-image-integration.md`. Run all quality gates,
then, with explicit authorization, commit/push CPS-1904 separately and record
paired hashes/refs.

## Done when

Snapshot and all consumer regressions pass, live snapshot/use/cleanup matches
CLI, runbook exists, and task commits are pushed.
