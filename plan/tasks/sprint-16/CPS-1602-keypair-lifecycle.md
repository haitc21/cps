# CPS-1602 — Project-owned keypair lifecycle

**Status:** Done
**Points:** 8
**Depends on:** CPS-1202, CPS-1203
**Paired task:** OPS-1602

## Outcome

Workspace users list, import, and delete Nova keypairs using public key
material only.

## Change set

- Add keypair inventory with provider/project identity, name, fingerprint,
  public-key algorithm, and bounded public material.
- Add import/delete contracts and API; integrate keypair ownership validation
  into VM create.
- Explicitly forbid generated/private key return and all private-key fields.
- Resolve same-name replay by fingerprint; conflicting fingerprints return 409.

## Required tests

- Public key validation and size bounds.
- Private key markers are rejected and redacted at every boundary.
- Duplicate import/delete, name collision, cross-project use, VM reference,
  refresh, and cleanup.

## Done when

An imported keypair boots a disposable SSH-accessible VM and no private material
appears in DB, messages, logs, fixtures, errors, or test output.

## Review evidence

- CPS migration `20260727_0015` applied successfully.
- CPS/OPS keypair unit and contract tests pass; Ruff passes for both services.
- Real curl/OpenStack acceptance passed for project-scoped import, inventory
  sync, public-only operation results, delete, tombstone projection, and
  provider cleanup. Direct OpenStack keypair list was empty after cleanup.
- Private-key markers are rejected and SDK responses are mapped before event
  serialization, so provider-only fields such as `private_key` are not
  published.
