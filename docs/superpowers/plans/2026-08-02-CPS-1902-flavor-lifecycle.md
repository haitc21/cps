# CPS-1902 Flavor Lifecycle and Project Access Implementation Plan

> **For agentic workers:** invoke `superpowers:using-superpowers`,
> `superpowers:using-git-worktrees`, and either
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`
> before implementation. Invoke `superpowers:test-driven-development` and
> follow every RED-GREEN-REFACTOR checkpoint below. The named Superpowers
> skills were not exposed to this planning session, so this document is the
> Codex-authored handoff; comments claiming skill use do not replace invocation.

**Task ID:** CPS-1902
**Branch/worktree:** `sprint-19/cps-1902` in the isolated CPS worktree
**Goal:** An authenticated CPS administrator can create and delete a Nova
flavor and replace its project access or patch its extra specs through durable,
idempotent CPS operations, with normalized inventory convergence and no unsafe
replace-on-update behavior.
**Paired task:** OPS-1902; CPS contracts are canonical and OPS pins their final
checksums before either task is Done.

## 1. Approved context and acceptance

Read before implementation:

- `AGENTS.md`, `/home/haitc/.codex/AGENTS.md`, and
  `/home/haitc/.codex/RTK.md`.
- `plan/README.md`, `plan/product-backlog.md`, `plan/sprints/sprint-19.md`, and
  `plan/tasks/sprint-19/CPS-1902-flavor-lifecycle.md`.
- `docs/ai/vibe-coding-workflow.md` and `docs/ai/review-checklists.md`.
- `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`
  and
  `docs/superpowers/specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`.
- Predecessor commit `b8a5ff7` and
  `docs/superpowers/plans/2026-08-01-CPS-1901-catalog-contracts.md`.
- Apache-2.0 behavioral references only (do not copy Django/novaclient code):
  `../opensource/horizon/openstack_dashboard/api/nova.py` and
  `../opensource/horizon/openstack_dashboard/dashboards/admin/flavors/`.

### Testable outcome

All of the following must be observable:

1. `POST /api/v1/admin/provider-connections/{connection_id}/flavors` accepts a
   Horizon-aligned bounded create body and returns `202` plus the durable
   operation/status URL.
2. `DELETE /api/v1/admin/provider-connections/{connection_id}/flavors/{flavor_id}`
   returns a durable operation only after CPS policy/dependency checks.
3. `PUT /api/v1/admin/provider-connections/{connection_id}/flavors/{flavor_id}/access`
   replaces the complete project access set. Input is a duplicate-free bounded
   list of provider project IDs that all belong to the same provider.
4. `PATCH /api/v1/admin/provider-connections/{connection_id}/flavors/{flavor_id}/extra-specs`
   atomically represents `set` and `unset`; the sets are disjoint, bounded,
   secret-free, and non-empty in aggregate.
5. Reusing an idempotency key with the same canonical request returns the same
   operation and produces one outbox command; different input returns stable
   `409 IDEMPOTENCY_KEY_REUSED`.
6. A successful create/access/extra-spec result upserts the normalized Flavor
   projection inside the same inbox transaction as operation completion;
   confirmed delete marks only that flavor `DELETED`. Duplicate events do not
   reapply state, and late results append immutable history without rewriting a
   terminal operation.
7. A member cannot call any mutation route. A non-`SYSTEM` connection, invalid
   or missing capability, cross-provider/missing project, duplicate name/ID,
   immutable sizing attempt, approved/in-use delete, stale/deleted flavor, and
   unsupported operation fail before command publication.

### Explicitly out of scope

- No generic mutable sizing/name/public-status PATCH and no Horizon-style
  delete/recreate update.
- No force delete, flavor migration, instance resize, image work, Nova SDK, or
  direct OpenStack I/O in CPS.
- No new authentication scheme, Keycloak role, DB table, typed flavor column,
  dependency, or image/upload path.
- No implicit catalog approval; create preserves an explicit false/default
  approval marker until the existing catalog policy changes it elsewhere.
- No physical purge of inventory/history and no deletion inferred from timeout,
  provider error, or an absent/stale CPS row.

## 2. Contract and API decisions

### Canonical contract/version

Add `cps.contracts.messages.flavor_operations` with strict typed request/result
models and the four operation names:

- `openstack.flavor.create`
- `openstack.flavor.delete`
- `openstack.flavor.access.replace`
- `openstack.flavor.extra_specs.patch`

The message envelope remains `schema_version: "1.0"`. This is an additive
minor-compatible message-family addition: existing messages and
`resource_operation.schema.json` remain valid, unknown major versions still
fail safely, and no current payload meaning changes. Add dedicated JSON Schema
and canonical request/result fixtures so OPS-1902 can pin exact checksums. Run
the manifest writer only after runtime and JSON Schema tests agree; do not edit
hashes by hand.

Create parameters are exactly:

- `name`: trimmed non-empty safe string, max 255;
- `provider_resource_id`: omitted/`null` means provider auto-allocation; the
  literal `auto` is normalized to `null` before fingerprinting; explicit IDs
  use Horizon's `[A-Za-z0-9. _-]+`, max 255;
- `vcpus`: strict integer `1..4096`;
- `ram_mib`: strict integer `1..16_777_216`;
- `root_disk_gib`: strict integer `0..1_048_576` (zero retains Nova's special
  image-size behavior);
- `ephemeral_disk_gib`: strict integer `0..1_048_576`, default zero;
- `swap_mib`: strict integer `0..16_777_216`, default zero;
- `is_public`: strict boolean;
- `access_project_ids`: required to be empty for public flavors; non-empty and
  duplicate-free for private flavors when initial restricted access is wanted;
- `extra_specs`: bounded safe string map, at most 128 entries; keys and values
  max 255; credential-like keys/values and unbounded nested values are rejected.

Access replacement uses `project_provider_resource_ids` (max 256, unique,
sorted only for canonical fingerprint/transport). It is allowed only for a
private flavor. An empty replacement is valid and means no project has access;
it does **not** make the flavor public. This deliberately differs from
Horizon's create-screen shortcut where no selected project implies public.

Extra-spec patch uses `{ "set": {...}, "unset": [...] }`; `unset` is unique,
max 128, and cannot overlap `set`. Empty patch is invalid. Provider-specific
extra-spec names remain opaque safe strings; CPS does not interpret Nova
scheduler semantics.

### Immutable sizing response

Do not register a generic flavor PATCH mutation. Assert OpenAPI has no such
operation and a request receives the framework's stable `405`. Application
tests also prove no service method/command exists for changing `name`, `vcpus`,
`ram_mib`, disks, swap, or `is_public`. The public explanation is: `Flavor core
fields are immutable; create a distinct flavor instead.` Add this text to the
OpenAPI descriptions and API test assertion without creating a replacement
operation.

### Authorization, scope, capability, and policy

- Routes live only on the existing `admin_router`, therefore use
  `require_admin`; member tokens must receive `403` and no DB/outbox mutation.
- The chosen provider connection must exist, be validated, have
  `scope_kind == SYSTEM`, and advertise the exact supported feature for the
  requested operation. Missing/false features return stable capability/scope
  errors before operation creation.
- Flavor identity is connection-scoped in storage but provider-global in
  semantics. Project access references resolve through canonical `Project`
  rows belonging to the same `provider_id`, not merely the same scoped
  connection, and must be live.
- Create rejects case-insensitive duplicate live flavor names and duplicate
  explicit provider IDs before publish. Provider races remain OPS/provider
  conflicts and converge to a safe failed operation.
- Delete rejects a flavor whose `catalog_approved` marker is true or whose
  provider ID is referenced by any non-deleted instance on the same provider.
  It also rejects missing/deleted inventory. No force flag exists.

## 3. Exact files and blast radius

CodeGraph was attempted first and reported no `.codegraph/` index in this
worktree. The following blast radius was established from direct source and
call-site inspection.

### Production and canonical artifacts

- Create `src/cps/contracts/messages/flavor_operations.py`: typed enums,
  create/access/extra-spec request validation, normalized result.
- Modify `src/cps/contracts/messages/__init__.py` only if public re-exports are
  repository convention.
- Modify `src/cps/contracts/messages/types.py`: four constants.
- Modify `src/cps/contracts/messages/delivery.py`: accepted command routing and
  retry/DLQ metadata allow-lists.
- Create `src/cps/contracts/jsonschema/flavor_operation.schema.json`.
- Create
  `src/cps/contracts/fixtures/flavor_operations/{create_request,access_replace_request,extra_specs_patch_request,delete_request,result}.json`.
- Modify `src/cps/contracts/semantic.py`,
  `src/cps/contracts/validate_contracts.py` only as needed to execute the new
  schema/fixture family.
- Modify `src/cps/contracts/checksums.json` via
  `python -m cps.contracts.write_manifest`.
- Create `src/cps/api/schemas/flavor.py`: REST bodies; exclude transport-owned
  IDs/scope.
- Modify `src/cps/api/routers/operations.py`: four admin endpoints, required
  `Idempotency-Key`, typed conversion, one UoW commit, admin status URL.
- Modify `src/cps/application/operations.py`: `create_flavor_operation`, scope,
  capability, identity/project/dependency guards, deterministic operation and
  message IDs, canonical payload, outbox draft, idempotent transition.
- Modify `src/cps/contracts/errors.py` and `src/cps/api/errors.py` only for
  provider-scope, immutable/dependency, or capability errors not already
  represented by a stable public error.
- Modify `src/cps/infrastructure/db/repositories/inventory.py`: provider-global
  project resolution, duplicate/dependency queries, and
  `persist_flavor_result`; reuse canonical `_upsert_resource` validation.
- Modify `src/cps/infrastructure/messaging/inbox_consumer.py`: project successful
  flavor create/access/extra-spec snapshots and confirmed delete tombstones in
  the existing inbox/UoW transaction.
- Modify `src/cps/infrastructure/messaging/topology.py` or constants only if the
  current explicit command/event binding list requires it; CPS publishes to the
  existing command topic exchange.
- No Alembic migration is planned: CPS-1901 already has typed sizing fields and
  bounded `provider_attributes.extra_specs/access_project_ids`. If a RED test
  proves a DB invariant cannot be safely enforced with current schema, stop and
  return to Planner before adding a migration.

### Tests

- Create `tests/contract/test_flavor_operation_contract.py`.
- Modify `tests/contract/test_delivery_contract.py` and
  `tests/contract/test_contract_manifest.py`.
- Create `tests/unit/api/test_flavor_operations.py`.
- Create `tests/unit/application/test_flavor_operations.py`.
- Create `tests/unit/infrastructure/db/test_flavor_operation_result_projection.py`.
- Create `tests/unit/messaging/test_inbox_flavor_projection.py`.
- Modify `tests/unit/messaging/test_event_routing_parity.py` and route/OpenAPI
  normalization tests as required.
- Create `tests/integration/db/test_flavor_operations.py` for transaction,
  duplicate/race, provider-global project resolution, dependency checks,
  projection, and tombstone behavior.
- Modify `tests/integration/messaging/test_inbox_dedupe.py` only if the existing
  generic duplicate fixture cannot express flavor results.

### Evidence

- Create `docs/runbooks/sprint-19-flavor-lifecycle.md` during verification.
- Modify `plan/tasks/sprint-19/CPS-1902-flavor-lifecycle.md` and
  `plan/sprints/sprint-19.md` only as gates advance; do not mark Done before the
  paired OPS pin/live evidence and both pushed refs exist.

Direct dependents to regression-test are the operation router/application
service, `MessageEnvelope`, delivery routing parity, transactional outbox,
event inbox dedupe/ack order, `InventoryRepository._upsert_resource`, catalog
admin/member projections, compatibility evaluation, and instance inventory
references. CPS must not import OpenStackSDK or Horizon modules.

## 4. Threat and reliability scope

No Codex Security plugin or security-diff workflow is used; it was removed by
direct user policy. Luna's second-pass review, repository secret scan, and the
following explicit threat scope remain mandatory:

- **Authorization bypass:** member calls, forged `SYSTEM` in request, invalid
  provider connection, and capability absence fail before outbox insertion.
- **Cross-provider mutation:** every flavor/project/provider identity is checked
  against the stored provider aggregate; names are never identity.
- **Duplicate destructive mutation:** canonical fingerprint plus deterministic
  operation/message IDs and provider-side OPS preconditions prevent repeated
  create/delete/access changes.
- **Partial access replacement:** CPS sends desired complete state; OPS-1902
  computes/rechecks a diff and returns the final snapshot. A partial provider
  result cannot be reported successful.
- **Unsafe delete:** approved or referenced live flavors fail closed; timeout,
  forbidden, service failure, or missing response never tombstones inventory.
- **Injection/secret leakage:** IDs, names, extra-spec keys/values, errors,
  result snapshots, logs, fixtures, and runbook are bounded and secret scanned;
  raw SDK objects/provider bodies/credentials are never serialized.
- **Stale/reordered events:** ownership validation, inbox message dedupe,
  terminal immutability, and late-event recording remain intact.
- **Resource exhaustion:** bound all maps/lists/strings, reject non-finite or
  non-strict numeric values, and preserve the existing envelope/event size
  limits.

## 5. Bite-sized RED-GREEN-REFACTOR sequence

Every checkbox group is a commit-sized coherent slice. The Worker must record
the exact RED command and the expected assertion/import/schema failure before
production code. If production is written first, revert that slice and restart
with its RED test.

### Slice A — Executable flavor contract

- [ ] Invoke `superpowers:test-driven-development`.
- [ ] RED: add contract tests for the four valid requests/results plus invalid
  empty/trimmed name, `auto` normalization, invalid ID characters, bool-as-int,
  negative/over-limit sizes, public-with-access, duplicate/oversized/cross-set
  access keys, empty patch, secret-bearing extra specs, extra fields, and
  unknown major. Run:
  `rtk pytest -q tests/contract/test_flavor_operation_contract.py`.
  Expected: import/schema/validation failures because the family is absent.
- [ ] GREEN: add the typed models, JSON Schema, fixtures, constants, delivery
  registration, semantic validation, and generated checksum entries only.
- [ ] Run:
  `rtk pytest -q tests/contract/test_flavor_operation_contract.py tests/contract/test_delivery_contract.py tests/contract/test_contract_manifest.py` and
  `rtk python -m cps.contracts.validate_contracts`.
- [ ] REFACTOR: share only existing safe string/map helpers; do not create a
  generic catalog-mutation abstraction without a second concrete use.

### Slice B — Create API through atomic outbox

- [ ] RED API/application tests: admin `202`, exact body/envelope/routing key,
  required idempotency header, member denial, missing/not-`SYSTEM` connection,
  false/missing capability, duplicate name/explicit ID, same-key replay, and
  changed-body conflict. Run:
  `rtk pytest -q tests/unit/api/test_flavor_operations.py tests/unit/application/test_flavor_operations.py -k create`.
  Expected: route/model/service absence.
- [ ] GREEN: add REST body, create route, guard queries, canonical request,
  deterministic operation/message IDs, `create_operation_idempotent`, outbox,
  and `ACCEPTED -> QUEUED` transition. Keep the route transaction owner as one
  UoW commit.
- [ ] RED DB integration: force operation insert/outbox insert failure in both
  directions and concurrent same-key requests. Expected: neither orphan row nor
  duplicate outbox survives; different payload returns conflict.
- [ ] GREEN: minimally adjust repository/UoW logic only if existing atomicity
  helpers do not already satisfy the tests.
- [ ] REFACTOR and rerun the create tests plus
  `tests/integration/db/test_unit_of_work.py` and
  `tests/integration/messaging/test_outbox_publish.py`.

### Slice C — Result projection and replay

- [ ] RED tests for successful create snapshot, duplicate completion, invalid or
  secret-bearing result, provider identity mismatch, late completion/failure,
  and create result without provider identity. Run:
  `rtk pytest -q tests/unit/infrastructure/db/test_flavor_operation_result_projection.py tests/unit/messaging/test_inbox_flavor_projection.py`.
  Expected: no flavor projection path.
- [ ] GREEN: add canonical `persist_flavor_result` and invoke it only for a
  validated successful flavor result, within the existing inbox transaction.
  Persist typed sizing plus bounded access/extra specs and set
  `catalog_approved: false` for newly created inventory unless a prior row's
  explicit policy must be preserved.
- [ ] REFACTOR: centralize result extraction in one private helper, preserving
  inbox dedupe, mark-processed, commit, then ack order.
- [ ] Run affected inbox, catalog, compatibility, and inventory projection
  suites.

### Slice D — Replace project access

- [ ] RED contract/API/application tests for private flavor success, public
  flavor conflict, missing/deleted/stale flavor, missing/deleted project,
  project on another provider, duplicate project ID, unchanged desired state,
  same-key replay, and changed-body conflict. Expected: route/service absence.
- [ ] GREEN: add the `PUT .../access` route and desired-state command. Resolve
  projects through their provider aggregate and publish only provider IDs; do
  not publish CPS UUIDs or credentials.
- [ ] RED result tests: final normalized access list replaces (not unions) the
  inventory list; duplicate/late events are safe; failed/partial results retain
  the prior projection.
- [ ] GREEN: project only a successful complete flavor snapshot.
- [ ] REFACTOR and run:
  `rtk pytest -q tests/unit/api/test_flavor_operations.py tests/unit/application/test_flavor_operations.py tests/unit/messaging/test_inbox_flavor_projection.py -k access`.

### Slice E — Patch extra specs

- [ ] RED tests for add/update/remove, mixed set/unset, overlap, empty patch,
  secret key/value, oversized map/list/string, missing/deleted flavor,
  capability denial, replay, and failure retaining the prior projection.
- [ ] GREEN: add the `PATCH .../extra-specs` route and desired patch command;
  update inventory only from OPS's final complete flavor snapshot.
- [ ] REFACTOR and run focused extra-spec contract/API/application/inbox tests.

### Slice F — Safe delete and immutable core

- [ ] RED tests for delete success, approved flavor conflict, live instance
  reference conflict (including another connection on the same provider),
  already deleted/missing flavor, same-key replay, provider failure/timeout not
  tombstoning, confirmed deletion tombstone, and duplicate delete completion.
- [ ] RED API/OpenAPI tests prove no generic sizing PATCH exists, it returns
  `405`, and the schema describes core fields as immutable.
- [ ] GREEN: add delete guard queries/route/command and extend confirmed-delete
  projection to `flavor`; never accept `force` and never tombstone from failure.
- [ ] REFACTOR and run delete tests plus catalog member/admin visibility and
  compatibility regressions.

### Slice G — Integration and failure matrix

- [ ] With disposable PostgreSQL 18, RED then GREEN integration tests for one
  transaction containing operation/event/outbox or inbox/projection; concurrent
  idempotency; duplicate message; worker restart/redelivery; out-of-order late
  result; invalid event rollback; and no tombstone after incomplete/failure.
- [ ] Run:
  `CPS_RUN_INTEGRATION=1 rtk pytest -q tests/integration/db/test_flavor_operations.py tests/integration/messaging/test_inbox_dedupe.py tests/integration/messaging/test_outbox_crash_recovery.py`.
- [ ] If any behavior requires a migration, stop for Planner review; otherwise
  assert `rtk alembic heads` remains a single existing head and fresh
  upgrade/downgrade/upgrade remains green.

## 6. Failure matrix

| Failure | CPS behavior | Inventory behavior |
|---|---|---|
| Missing/invalid admin auth | 401/403 before UoW mutation | unchanged |
| Connection absent/non-SYSTEM/unvalidated | stable precondition error, no outbox | unchanged |
| Capability missing/unsupported | stable capability error, no outbox | unchanged |
| Duplicate live name/explicit ID | stable 409, no outbox | unchanged |
| Same idempotency key, same request | return original operation | one command/result |
| Same key, different request | `IDEMPOTENCY_KEY_REUSED` | unchanged |
| Cross-provider/missing project | not-found/scope error, no outbox | unchanged |
| Public flavor access replacement | stable conflict | unchanged |
| Approved or live-instance-used delete | stable dependency conflict | unchanged |
| Outbox publish crash | committed row remains retryable | unchanged |
| OPS/provider validation/conflict/forbidden | terminal FAILED with safe error | unchanged |
| Timeout/restart before terminal result | retry/reconcile; no inferred success/delete | unchanged |
| Duplicate completion | inbox duplicate acked without reapply | one projection |
| Completion payload invalid/secret-bearing | transaction rollback; retry/DLQ policy | unchanged |
| Completion after terminal state | immutable late-result event | terminal projection unchanged |
| Confirmed delete | SUCCEEDED | exact flavor tombstoned |

## 7. Review and verification gates

- [ ] Invoke `superpowers:requesting-code-review` after Worker implementation.
- [ ] Reviewer Luna pass 1 independently checks specification, acceptance,
  exact API/contract/version, CPS/OPS boundary, and out-of-scope compliance.
- [ ] Reviewer Luna pass 2 independently checks authorization, capability,
  idempotency/races, destructive guards, event ordering, safe result parsing,
  transaction/ack semantics, tests, maintainability, and secret handling.
- [ ] Invoke `superpowers:receiving-code-review`; technically validate every
  finding, fix valid findings, rerun affected tests, and obtain final Luna
  re-approval. Per global policy, if the same task needs more than three
  Worker–Reviewer remediation cycles or a finding recurs, move only the
  remaining CPS-1902 remediation to Codex GPT-5.6 Sol; CPS-1903 resets to Cursor
  Composer.
- [ ] Invoke `superpowers:verification-before-completion`.
- [ ] Run fresh focused and full gates:

```bash
rtk ruff check src tests
rtk mypy src
rtk pytest -q
CPS_RUN_INTEGRATION=1 rtk pytest -q -m integration
rtk python -m cps.contracts.validate_contracts
rtk alembic heads
rtk git diff --check
rtk detect-secrets scan --all-files
```

Expected: every command exits zero, exactly one Alembic head, no verified new
secret, and no skipped task-specific test. Preserve fresh redacted summaries.

## 8. Live curl/OpenStack verification and cleanup

Use host Python processes for CPS/OPS when simpler; Docker application
containers are not required. Keep only PostgreSQL/RabbitMQ/Keycloak and the
minimum KVM node needed. Do not start TMS/BMS/LMS or `compute02` for this task.
Use task-scoped environment variables and never print tokens/passwords.

- [ ] Start CPS API/worker and paired OPS-1902 worker, verify readiness and
  Rabbit queues/consumers. Capture versions and final contract checksum only.
- [ ] Choose a validated `SYSTEM` connection and two existing disposable test
  projects from the same provider. Record IDs only.
- [ ] Set a unique `FLAVOR_NAME="cmp-s19-$(date +%s)"` and idempotency keys.
- [ ] `curl -X POST` the admin flavor create endpoint with a private flavor,
  explicit bounded sizing, both test project IDs, and one harmless extra spec.
  Poll `GET /api/v1/admin/operations/{id}` every five seconds to terminal
  `SUCCEEDED`; any FAILED/TIMED_OUT/CANCELLED blocks acceptance.
- [ ] Independently run `openstack flavor show "$FLAVOR_ID" -f json`,
  `openstack flavor access list "$FLAVOR_ID" -f json`, and
  `openstack flavor extra spec list "$FLAVOR_ID" -f json`. Compare provider ID,
  name, vCPU, RAM, root/ephemeral/swap, public flag, exact project-ID set, and
  exact safe extra-spec set with CPS admin detail.
- [ ] Replay the identical create request/key and prove the same operation and
  one provider flavor. Reuse the key with altered RAM and require 409/no second
  flavor.
- [ ] Replace access through CPS with one project; poll success and compare the
  exact set through CPS and OpenStack CLI. Replay once.
- [ ] Patch extra specs through CPS with one update, one add, and one removal;
  poll and compare exact final maps through both systems. Replay once.
- [ ] Exercise negative live checks before cleanup: member mutation denial,
  generic core PATCH `405`, and delete conflict while temporarily approved or
  referenced only if a disposable safe setup exists. Do not mutate pre-existing
  instances/catalog policy merely to manufacture evidence.
- [ ] Delete the task-created flavor through CPS, poll terminal success, require
  `openstack flavor show "$FLAVOR_ID"` to return not found, trigger targeted
  flavor refresh if required, and prove CPS detail is tombstoned/hidden from
  default lists. Repeat delete only when the designed absent behavior can be
  proven without widening scope.
- [ ] Query provider ID/name sets before and after and prove no `cmp-s19-*`
  flavor remains. Remove only task-created resources and all task response files
  under `/tmp`. Stop host CPS/OPS processes and unnecessary containers; leave
  shared pre-existing infrastructure untouched.
- [ ] Write `docs/runbooks/sprint-19-flavor-lifecycle.md` with redacted exact
  commands, exit codes/test totals, schema/checksum, Luna approvals, secret-scan
  disposition, operation/correlation/provider IDs, field comparisons, replay
  evidence, failure cases, cleanup ledger, limitations, and CPS/OPS commit refs.
  Never include credentials, tokens, headers, private keys, unsafe raw provider
  bodies, `clouds.yaml`, binary artifacts, or user data.

## 9. Proposed commit boundaries and Git gate

Prepare these reviewable boundaries; combine only if final review concludes a
single atomic commit is clearer:

1. `feat(contracts): define durable flavor operations` — contracts, fixtures,
   schemas, delivery registration, checksum, contract tests.
2. `feat(flavors): add admin lifecycle operations` — REST/application guards,
   outbox, result projection, unit/integration tests.
3. `docs(flavors): record CPS-1902 acceptance evidence` — runbook and task/sprint
   evidence only.

- [ ] Invoke `superpowers:finishing-a-development-branch`.
- [ ] Run `rtk git status --short`, `rtk git diff --check`,
  `rtk git diff --stat`, and inspect the complete staged candidate for unrelated
  files/secrets/artifacts.
- [ ] Git mutation requires the user's exact authorization for this execution
  turn under repository/global policy. If authorized, commit only CPS-1902,
  push `sprint-19/cps-1902`, and report branch, hashes, remote refs, and clean
  status. Otherwise stop with the proposal; do not stage/commit/push.
- [ ] Do not mark CPS-1902 Done until OPS-1902 pins the final canonical hashes,
  both live sides pass, cleanup is zero-residual, both refs are pushed, and the
  runbook links them.

## Plan self-review

- [x] Story, testable acceptance, dependencies, and out-of-scope are explicit.
- [x] Horizon semantics and intentional deviations are documented.
- [x] Exact interfaces/files/callers and no-migration decision are named.
- [x] Contract version and OPS checksum pin decision are explicit.
- [x] Authorization, capability, delete, replay, event, and secret threat scope
  is covered without using the removed Codex Security workflow.
- [x] Every production slice begins with an observable RED failure and includes
  minimal GREEN, refactor, focused/full commands, and failure behavior.
- [x] Luna two-pass review, >3-cycle Sol escalation, verification, secret scan,
  live curl/CLI comparison, cleanup, runbook, and commit boundaries are exact.
- [x] No unresolved placeholder or production-code authorization is hidden in
  this plan.
