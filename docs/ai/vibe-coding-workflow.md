# CPS AI-Assisted Delivery Workflow

This workflow turns a Scrum story into a small, reviewable, evidence-backed increment. It is optimized for AI pairing without sacrificing architecture, tests, or operational safety.

## 1. Select and frame the story

- Work from the active Sprint Backlog.
- Record story ID, sprint goal, acceptance criteria, dependencies, and out-of-scope items.
- If the requested change alters architecture, contract semantics, or scope, update/approve design first.
- Prefer one vertical behavior over a broad layer scaffold.

Output before implementation:

```text
Story: CPS-xxx
Outcome:
Acceptance criterion being implemented:
Files/boundaries expected:
OPS dependency:
Risks:
Verification:
```

## 2. Discover with CodeGraph and RTK

From the CMP workspace root, use CodeGraph for symbols, callers, persistence flow, API-to-service flow, and message flow. Then use RTK-prefixed `rg` for exact contract keys/configuration and `rtk git status --short` for worktree state.

Discovery must answer:

- Which public/internal interface changes?
- Which callers/consumers depend on it?
- Which transaction owns the change?
- What can be duplicated, retried, reordered, or partially fail?
- What secret-bearing values pass through it?

## 3. Make the contract executable

For boundary changes, create the schema/example first. Add a failing test demonstrating both valid and invalid input. Decide compatibility and version behavior explicitly. Update OPS coordination notes before implementation diverges.

## 4. Slice vertically

Implement the smallest end-to-end path through:

```text
API/message -> application use case -> domain rule -> port/repository -> adapter -> response/event
```

Do not create generic abstractions without a current second use. Keep domain logic independent of FastAPI, SQLAlchemy, aio-pika, and provider-specific concepts.

## 5. Develop test-first

Use this test order:

1. Domain/unit test for rules and state transitions.
2. Contract test for API/message representation.
3. Repository/transaction integration test when persistence changes.
4. RabbitMQ integration test when delivery semantics change.
5. End-to-end test only after the lower layers isolate failures.

Always observe the new test fail before implementation.

## 6. Perform failure-first review

Before considering the happy path complete, test:

- duplicate request/message;
- retry after partial provider/DB/message success;
- timeout and restart;
- stale optimistic version;
- invalid state/capability;
- missing referenced resource;
- incomplete inventory sync;
- secret-bearing invalid input;
- out-of-order or unknown contract version.

## 7. Verify and hand off

Run focused then full quality gates using RTK. Inspect diff and CodeGraph blast radius where indexed. Update docs, fixtures, migration notes, and Sprint Review evidence.

Completion report must include:

- outcome and story ID;
- changed contracts/migrations;
- tests and exact results;
- security/reliability checks;
- known limitations or follow-up backlog IDs;
- commit hash if committed.

## Vibe-coding guardrails

- A plausible implementation is not evidence; a passing targeted test is evidence.
- Generated volume is not progress; completed acceptance criteria are progress.
- Never ask the model to “implement the whole epic” in one change.
- Stop and re-scope when context becomes too broad to explain transaction and failure boundaries.
- Prefer explicit names and small modules over framework magic.
- Preserve design intent even when a shortcut appears faster.
