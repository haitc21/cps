# CPS-1903 — Image metadata, access, and lifecycle

**Status:** Blocked — no configured allowlisted HTTPS lab source
**Points:** 13  
**Paired task:** OPS-1903  
**Depends on:** CPS-1901

## Outcome

An authorized administrator manages Glance image metadata, visibility, member
access, activation state, approved URL import, and deletion through durable CPS
operations without transporting image bytes or credentials.

## Deliverables

- Admin APIs/contracts for create/import-from-provider-accessible URL, metadata
  patch, visibility/protected update, member grant/revoke, deactivate,
  reactivate, and delete.
- Fields follow Horizon semantics where provider-neutral: name, description,
  disk/container format, architecture, kernel/ramdisk IDs, minimum disk/RAM,
  visibility (`private`, `shared`, `community`, `public`), protected, tags, and
  bounded custom properties.
- Validate URL scheme/length with an explicit source policy; reject embedded
  credentials, signed/private query credentials, local/file schemes, image
  bytes, and secret-like metadata. Capability-gate URL import.
- Enforce admin/user authorization, owner/project/member scope, protected and
  status preconditions, launchable format rules, and catalog approval policy.
- Persist operation/outbox atomically; accept asynchronous Glance states and
  reconcile with bounded terminal handling; update/tombstone inventory only
  from confirmed provider evidence.

## Tests first

- Contract/API tests for all operations, status transitions, visibility/member
  combinations, protected delete, invalid format/minimums, malicious URLs,
  secret properties, unsupported import, idempotency conflict, and authorization.
- Operation/DB/messaging tests for queued/importing/active/killed/deactivated,
  duplicate/redelivery, late result, timeout, outbox failure, and stale refresh.

## AI/Superpowers workflow

**Mandatory skill chain:** `superpowers:using-superpowers` →
`superpowers:brainstorming` → `superpowers:writing-plans` →
`codex-security:threat-model` → `superpowers:using-git-worktrees` →
`superpowers:subagent-driven-development` or `superpowers:executing-plans` →
`superpowers:test-driven-development` →
`superpowers:requesting-code-review` / `superpowers:receiving-code-review` →
`codex-security:security-diff-scan` →
`superpowers:verification-before-completion` → live curl/CLI/runbook →
`superpowers:finishing-a-development-branch`. Brainstorming and threat modeling
are unconditional here because URL import, metadata, visibility, member access,
and deletion cross security boundaries. Critical/High findings block completion.

1. **Planner — Codex ChatGPT 5.6 sol:** study Horizon image forms/actions/API,
   CPS design prohibiting binary transfer, CodeGraph operation/catalog callers,
   and OpenStack capability boundaries. Produce operation/state table, threat
   model, contract/version plan, red tests, curl/CLI workflow, cleanup, and
   commit boundaries. URL import remains blocked until this plan is approved.
2. **Worker — Cursor Composer 2.5 Fast:** add failing contracts/security tests,
   update canonical schemas/fixtures/checksum/OpenAPI, then implement one API →
   durable operation/outbox slice at a time. Do not fetch or proxy source data.
3. **Reviewer — Codex ChatGPT 5.6 luna:** independently review SSRF/credential
   exposure, authorization, metadata bounds, visibility/member semantics,
   status/protected guards, idempotency, asynchronous timeout/reconciliation,
   redaction, and OPS pinning. Critical/high findings block execution.
4. Worker resolves findings and reruns tests; Reviewer performs second approval.

## Verification, runbook, and Git gate

1. Run contract/security/API/application/DB/messaging/migration tests, Ruff,
   MyPy, full CPS suite, diff check, and secret scan.
2. Use a non-secret lab HTTP image source approved for testing. By `curl`,
   submit import, poll to terminal, show/patch image, grant/revoke a disposable
   project member, deactivate/reactivate, protect/unprotect, and delete.
3. After every CPS operation, verify IDs and fields with `openstack image show`,
   `image member list`, and suitable image set/unset/delete commands. Confirm
   deactivated/protected behavior and final not-found plus CPS tombstone.
4. Write `docs/runbooks/sprint-19-image-lifecycle.md` with a redacted source URL,
   operation timeline, CLI comparison, negative tests, and cleanup ledger.
5. After explicit Git authorization, commit/push CPS-1903 separately and record
   CPS/OPS hashes and refs. Never commit image artifacts or signed URLs.

## Done when

Security, replay, lifecycle, and live CPS/CLI checks pass; no bytes/credentials
cross the durable boundary; cleanup is complete; runbook and commits exist.
