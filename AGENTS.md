# CPS AI Agent Rules

These instructions apply to every AI-assisted change in this repository. They complement the approved design and Scrum plan; when instructions conflict, use this order: direct user request, this file, approved design, active Sprint Backlog, product backlog, general conventions.

## Mandatory context before work

1. Read `docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md` for architecture and scope.
2. Read `plan/README.md`, `plan/product-backlog.md`, and the active `plan/sprints/sprint-<n>.md` when Sprint Planning has created one.
3. Identify the story ID and restate its acceptance criteria before changing files.
4. Check `git status --short` and preserve unrelated user changes.
5. Follow `docs/ai/vibe-coding-workflow.md` and the checklists in `docs/ai/review-checklists.md`.

Do not implement a backlog item that is not selected into the active Sprint Backlog unless the user explicitly changes priority. Do not silently expand a story.

## CodeGraph-first discovery

The CMP workspace may contain `.codegraph/` at its root. When it exists and code understanding or location is required:

1. Run from the workspace root:

   ```powershell
   codegraph explore "<symbols or focused question>"
   codegraph node <symbol-or-file>
   ```

2. Use the returned source/call paths before `rg`, directory enumeration, or manual file reading.
3. Use `rg` only for exact text, configuration, non-code assets, or when CodeGraph returns no relevant indexed result.
4. State when the index appears stale; do not invent relationships. Re-indexing is a user/workspace decision unless explicitly requested.
5. Before modifying a symbol, inspect callers/dependents and identify the blast radius. After modification, test that radius.

If no applicable `.codegraph/` exists, skip CodeGraph without creating one.

## RTK command policy

Prefix supported external commands with `rtk` to reduce tool output, for example:

```powershell
rtk git status --short
rtk rg "pattern" src tests
rtk pytest -q
rtk docker compose ps
```

RTK does not resolve PowerShell cmdlets such as `Get-ChildItem` or `Get-Content`; use those cmdlets directly when needed. Use other direct external commands only when RTK is unavailable, blocked, or changes semantics, and say why in the work log. Do not run `rtk init -g` or modify global hooks without explicit user authorization. Never let output filtering replace checking the real exit code.

## Architectural boundaries

- CPS is the provider-neutral control plane and PostgreSQL source of truth.
- CPS must not import OpenStackSDK or encode Nova/Neutron/Cinder/Glance behavior.
- OPS is accessed through versioned contracts and RabbitMQ, except the internal credential-resolution boundary.
- Credentials are referenced in messages, encrypted at rest, redacted everywhere, and never returned by public APIs.
- Every mutation is a durable operation with idempotency and immutable history.
- Database/message reliability uses transactional outbox and inbox patterns.
- Inventory uses typed tables, provider identity, soft deletion, and safe full-sync finalization.
- Valkey and MongoDB are not CPS runtime dependencies in the current scope.
- Keycloak, TMS, MS, LMS, and VMware are extension points, not current implementation scope.

## Contract-first rule

For any API or message change:

1. Add or update the acceptance example and failing contract test.
2. Change canonical Pydantic/OpenAPI/JSON Schema in CPS.
3. Preserve compatibility or explicitly increment `schema_version`.
4. Update golden fixtures and checksum manifest.
5. Coordinate the pinned OPS copy and its tests in the same sprint.
6. Implement producer and consumer behavior only after the contract is executable.

Unknown major versions must fail safely. Additive compatible fields must not break consumers. Never serialize ORM objects, SDK objects, exceptions, credentials, tokens, or raw unsafe provider bodies.

## Test-driven implementation

Use red-green-refactor for every behavior change:

1. Write the smallest failing unit/contract/integration test proving the acceptance criterion.
2. Run it and confirm failure for the expected reason.
3. Implement the minimum coherent behavior.
4. Run the focused test, then the affected suite.
5. Refactor only while tests remain green.
6. Run the full Definition of Done gates before claiming completion.

Bug fixes require a regression test. Do not weaken assertions or delete tests to make a build pass.

## Database changes

- Use SQLAlchemy 2 patterns and Alembic; never mutate schema manually as the implementation.
- Every model change includes migration, constraint/index review, repository tests, and clean PostgreSQL 18 upgrade verification.
- Prefer database-enforced uniqueness and integrity for idempotency and provider identity.
- Never mark missing inventory deleted from an incomplete or failed sync.
- Migrations must be deterministic and avoid embedding secrets or environment-specific IDs.
- Destructive migration or data reset requires explicit user authorization and a rollback/data-preservation plan.

## Messaging and concurrency

- Publish persistent messages with confirms; acknowledge consumed events only after the DB transaction succeeds.
- Make handlers idempotent under duplicate/redelivered messages.
- Preserve `message_id`, `correlation_id`, `causation_id`, `operation_id`, and `idempotency_key` semantics.
- Bound concurrency, retries, timeouts, and payload/batch size.
- Classify transient versus permanent failures; poison messages must terminate in DLQ.
- Never infer provider deletion from timeout, authentication failure, or service unavailability.

## Security and privacy

- Treat password, token, authorization header, CA private material, and VM `user_data` as secrets.
- Do not print, commit, snapshot, fixture, trace, or include secrets in exceptions.
- Use synthetic values in tests and `.env.example`; real `.env` remains ignored.
- Public API initially has no auth only because deployment is internal; keep an authorization dependency boundary.
- Internal credential resolution must remain separate from public ingress.

## Python and dependencies

- Use CPython 3.12 and the repository lockfile.
- CPS uses FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Psycopg 3, RabbitMQ/aio-pika; it does not depend on OpenStackSDK.
- Add a dependency only when standard library/current dependencies cannot reasonably solve the problem. Explain its maintenance/security impact.
- Never float runtime dependencies. Update lockfiles intentionally and verify affected integration tests.

## Git and completion discipline

- Keep commits scoped to one story or coherent vertical slice.
- AI agents must not stage, commit, amend, merge, rebase, or push unless the user explicitly requests that exact Git operation in the current turn. Authorization from an earlier turn does not carry forward.
- A plan step named `Commit` means prepare a commit proposal and stop for approval; it does not authorize `git add` or `git commit`. Requests such as "continue", "finish", or "execute the plan" do not imply Git authorization.
- Never reset, discard, or overwrite unrelated changes.
- Do not commit secrets, generated caches, local data volumes, or test artifacts.
- Before completion run the commands defined by the repository; until scaffolded, at minimum run `rtk git diff --check` and validate changed Markdown/YAML/Compose files.
- Report exact tests/commands and outcomes. Do not claim passing, fixed, or complete without fresh evidence.
- Update the active Sprint Backlog status and review evidence when a story reaches Done.
