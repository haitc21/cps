# CPS-1301 — Persist provider identity and terminal events

## Goal

Persist the Nova server identity before optional OPS enrichment and consume
terminal results idempotently so a partial result-publication sequence cannot
leave CPS without enough information to recover.

## Scope

- Extend the canonical create-progress payload with `provider_resource_id`,
  provider status, stage, and safe diagnostic metadata.
- Persist the provider resource ID on the operation and pending instance
  projection without declaring the operation successful.
- Keep progress and terminal message identities deterministic under redelivery.
- Apply completed/failed events atomically to the operation, event history, and
  normalized instance/relationship projections.
- Preserve immutable terminal-state and late-result semantics.
- Add contract fixtures and migration only if the current operation/result
  storage cannot retain the early provider identity.

## Acceptance

- Progress carrying a Nova server ID survives CPS restart and is queryable
  before the operation becomes terminal.
- Duplicate progress and terminal events have no additional domain effect.
- Completed publication can be retried after progress was already accepted.
- A late terminal event is retained without silently overwriting terminal
  operation history.
- Provider credentials, tokens, user data, and raw SDK objects never enter the
  contract, database diagnostics, or logs.

## Verification

- Contract fixture and checksum tests.
- Operation state-machine and inbox deduplication tests.
- Database upgrade/downgrade test when a migration is required.
- Integration test for progress accepted followed by delayed completed event.
