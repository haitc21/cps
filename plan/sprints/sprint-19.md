# Sprint 19 — Horizon-parity image and flavor administration

**Status:** Done with explicit 1905 restart/failure-path waiver
**Dates:** 2026-08-03 to 2026-08-14
**Capacity:** 34 CPS points
**Sprint Goal:** An authorized cloud administrator can inspect and safely
manage Nova flavors and Glance image metadata/access through durable CPS/OPS
operations, with every delivered vertical slice verified through CPS API and
the OpenStack CLI.

**Source references:** Horizon behavior in `../opensource/horizon`, especially
`openstack_dashboard/api/nova.py`, `api/glance.py`,
`dashboards/admin/flavors/`, and `dashboards/project/images/`.

## Scope decisions

- Reuse Horizon's field semantics, validation cases, policy names, filters,
  status rules, and test scenarios where compatible and covered by Apache-2.0.
- Do not import Django, novaclient, glanceclient, or Horizon UI code into CPS.
  CPS remains provider-neutral; OPS implements provider behavior with supported
  OpenStackSDK APIs.
- Do not copy Horizon's flavor PATCH implementation that deletes and recreates
  a flavor. Core flavor sizing fields are immutable after creation in this
  sprint; access and extra specs are updated explicitly.
- Image binary upload and signed/private source credentials are out of scope.
  Image bytes never traverse CPS, PostgreSQL, RabbitMQ, logs, or fixtures.
  Provider-accessible URL import is enabled only after capability and security
  review. A streaming upload needs a separately approved data-plane design.
- Existing curated-catalog enforcement remains fail closed. Admin mutation and
  user catalog selection are separate authorization surfaces.

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1901 Catalog detail and compatibility contracts | 5 | CPS | OPS-1901 | Done |
| CPS-1902 Flavor lifecycle and project access | 8 | CPS | OPS-1902 | Done |
| CPS-1903 Image metadata, access, and lifecycle | 13 | CPS | OPS-1903 | Done |
| CPS-1904 Instance image snapshot and consumer integration | 5 | CPS | OPS-1904 | Done |
| CPS-1905 Cross-service acceptance and release evidence | 3 | CPS/OPS | OPS-1905 | Done (waived restart/failure path) |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1901](../tasks/sprint-19/CPS-1901-catalog-contracts.md) | Detailed image/flavor query contracts and compatibility validation | CPS-1703 | Done |
| [CPS-1902](../tasks/sprint-19/CPS-1902-flavor-lifecycle.md) | Durable flavor create/delete/access/extra-spec operations | CPS-1901 | Done |
| [CPS-1903](../tasks/sprint-19/CPS-1903-image-lifecycle.md) | Durable image metadata/import/member/state/delete operations | CPS-1901 | Done |
| [CPS-1904](../tasks/sprint-19/CPS-1904-instance-image-integration.md) | Instance snapshot plus launch/rebuild/volume compatibility checks | CPS-1901, CPS-1903 | Done |
| [CPS-1905](../tasks/sprint-19/CPS-1905-catalog-acceptance.md) | Real-cloud matrix, runbooks, checksums, and cleanup | CPS-1902..1904 | Done (waived restart/failure path) |

## Mandatory AI delivery protocol for every task

The installed Superpowers and Codex Security plugins are mandatory workflow
dependencies. Agents must invoke the named skills, not merely imitate them:

1. Invoke `superpowers:using-superpowers`, then
   `superpowers:brainstorming` when requirements/design still contain a choice,
   and `superpowers:writing-plans`. Save the implementation micro-plan under
   `docs/superpowers/plans/YYYY-MM-DD-<task-id>-<slug>.md` with exact files,
   bite-sized checkbox steps, failing-test commands/expected failures, minimal
   implementation steps, verification commands, and commit boundaries.
2. **Planner — Codex ChatGPT 5.6 sol:** read both `AGENTS.md` files, canonical
   design, active sprint/task, CodeGraph blast radius, Horizon references, and
   current git status. Produce a task-scoped implementation plan, contract
   compatibility decision, red/green test list, failure matrix, exact curl and
   OpenStack CLI verification, cleanup, and proposed commit boundaries.
3. Before implementation, use `codex-security:threat-model` to generate or
   validate the repository-scoped threat model and add task-specific abuse
   cases. Security approval is required for new admin routes, URL import,
   metadata, project access, and destructive operations.
4. At execution time invoke `superpowers:using-git-worktrees`; implement in an
   isolated task worktree/branch. Use either
   `superpowers:subagent-driven-development` (preferred) or
   `superpowers:executing-plans` to execute the approved micro-plan.
5. **Worker — Cursor Composer 2.5 Fast:** invoke
   `superpowers:test-driven-development` and implement only the approved task
   with strict red-green-refactor. Start with an observed failing test, then the
   smallest vertical slice. Reuse compatible Horizon semantics/tests, preserve
   CPS/OPS boundaries, and record every deviation.
6. Invoke `superpowers:requesting-code-review` for handoff.
   **Reviewer — Codex ChatGPT 5.6 luna:** independently inspect the diff,
   contract checksum/pinned copy, CodeGraph blast radius, authorization,
   idempotency/replay, timeout/error normalization, secret handling, migration,
   and tests. Critical/high findings return the task to Worker.
7. Worker invokes `superpowers:receiving-code-review`, verifies each finding
   technically, fixes valid findings, and reruns focused/affected suites.
   Reviewer gives a second approval.
8. Run `codex-security:security-diff-scan` against the task Git diff. It must
   execute threat-model, finding-discovery, validation, and attack-path phases
   as applicable and produce its canonical report. Triage/fix/track every
   reportable finding; unresolved Critical/High blocks live testing and commit.
9. Invoke `superpowers:verification-before-completion`, run repository quality
   gates, and preserve fresh command output. Then run a live task-specific
   `curl` against
   CPS, poll the durable operation to terminal success, and independently query
   the same provider resource with `openstack` CLI. Compare IDs and material
   fields; API success alone is not acceptance.
10. Clean disposable resources and verify absence with both CPS reconciliation
   and OpenStack CLI. Never delete pre-existing resources.
11. Add a redacted runbook under `cps/docs/runbooks/`, update task and sprint
   evidence, inspect `git diff --check`, and run secret scanning.
12. Invoke `superpowers:finishing-a-development-branch`. Commit and push one
   task-scoped change in each affected repository only
   after all gates pass and explicit Git authorization is confirmed for that
   execution turn. Record branch, commit hashes, remote refs, commands, output
   summaries, resource IDs, and cleanup result in the runbook.

## Execution sequence

1. CPS-1901/OPS-1901 establish canonical contracts and richer inventory.
2. CPS-1902/OPS-1902 deliver flavor operations independently of image work.
3. CPS-1903/OPS-1903 deliver image metadata/access/state operations; URL import
   remains capability-gated.
4. CPS-1904/OPS-1904 add Nova instance snapshot and enforce image/flavor
   compatibility at every consumer.
5. CPS-1905/OPS-1905 run the full replay, recovery, real-cloud, and cleanup
   matrix and publish release evidence.

## Sprint acceptance

- Flavor list/detail/filter, create, delete, project access, and extra specs
  work through CPS/OPS without unsafe replace-on-update behavior.
- Image list/detail/filter, metadata/visibility/protection, member access,
  deactivate/reactivate, delete, approved URL import, and instance snapshot
  have durable, replay-safe outcomes.
- Launch, rebuild, resize, and volume-from-image reject stale, unapproved, or
  incompatible image/flavor references before publication.
- Every task has deterministic automated evidence plus one successful live
  `curl`/OpenStack CLI comparison, a cleanup check, a runbook, and task-scoped
  CPS/OPS commit hashes.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Flavor core fields are not safely mutable | Make sizing immutable; expose explicit access/extra-spec updates only |
| URL import can expose credentials or SSRF paths | Allow only provider-accessible non-secret URL data after design review; redact/reject credentials |
| Glance import/deactivate/member APIs vary by cloud | OPS capability discovery and explicit `UNSUPPORTED`, never release-name checks |
| Duplicate create/import creates extra resources | Operation marker plus deterministic lookup and provider-state preconditions |
| Admin endpoints weaken curated user policy | Separate admin authorization dependency and keep user catalog read-only |

## Review evidence

- Contract checksum:
- Focused/full quality gates:
- Live CPS API/OpenStack CLI comparisons:
- Cleanup ledger:
- Runbooks:
- CPS/OPS commit and pushed refs:
