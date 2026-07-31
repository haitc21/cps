# CPS-1201 — Provider-owned encrypted credential

**Status:** Done
**Active backlog:** No — provider-owned credential migration, contracts, and
full PostgreSQL lifecycle evidence are complete.
**Points:** 13  
**Depends on:** none  
**Paired task:** OPS-1201  
**Design:** `../../../docs/superpowers/specs/2026-07-26-provider-tenancy-authorization-design.md`

## Outcome

One provider owns exactly one encrypted OpenStack administrative credential.
Connections represent only scope/region. CPS exposes no standalone credential
resource and publishes no credential identifier to OPS.

## Change set

### Database and migration

- Add encrypted username/password, nonces, key version, user domain, and rotated
  timestamp to `providers`.
- Validate that every legacy provider references at most one distinct
  credential before backfill.
- Backfill provider secret fields through `provider_connections` when legacy
  rows exist.
- Abort migration on ambiguous one-provider/multiple-credential data.
- Remove `provider_connections.credential_id`, its index, and FK.
- Drop `credentials` only after provider columns are populated and constrained.
- Provide downgrade behavior and clean-database lifecycle coverage.

### Domain, repository, and security

- Replace the provider/connection/credential tuple with a provider aggregate
  containing encrypted secret fields and scoped connections.
- Change AES-GCM AAD identity from credential ID to provider ID.
- Resolve a secret from `provider_connection_id -> provider_id`.
- Rotate username/password atomically with provider optimistic locking.
- Mark all connections of the provider `PENDING_VALIDATION` after rotation.
- Preserve key-version and nonce uniqueness checks.

### API and contracts

- Keep username/password as write-only fields of provider create/update.
- Remove credential router, schemas, service, public OpenAPI paths, and
  credential-specific errors.
- Remove `credential_id` from connection create/update schemas.
- Remove `credential_reference` from operation commands, validation messages,
  JSON schemas, examples, and golden fixtures.
- Keep provider views secret-free and expose only safe metadata such as
  `user_domain_name` and credential-present/rotated state when required.

### Cleanup

- Remove obsolete ORM exports, dependency injection wiring, repositories, seed
  helpers, and credential CRUD tests.
- Update architecture and operational documentation.

## Implementation order

1. Add failing schema metadata, migration, aggregate, and redaction tests.
2. Add migration and provider ORM fields while retaining compatibility.
3. Refactor repository and provider service to the new aggregate.
4. Refactor resolver and connection services.
5. Update CPS canonical contracts and fixtures.
6. Remove the old API/model/table code.
7. Run migration lifecycle and full quality gates.
8. Hand the canonical contract checksum to OPS-1201.

## Required tests

- Provider create persists ciphertext, never plaintext.
- Provider supports multiple connections without duplicate credentials.
- Rotation changes ciphertext/nonces and invalidates all connections.
- Missing encryption key fails closed.
- Optimistic-lock conflict rolls back the whole rotation.
- Resolver rejects connection/provider mismatch and missing provider.
- Legacy unambiguous migration succeeds.
- Legacy ambiguous migration aborts without partial schema mutation.
- OpenAPI contains no `/credentials` route.
- Serialized commands contain no credential reference or decrypted secret.

## Verification

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

## Done when

- `credentials` and `provider_connections.credential_id` no longer exist.
- Provider creation, update, validation, inventory, and operations resolve the
  same provider-owned secret.
- CPS/OPS canonical fixtures contain no credential identifier.
- Secret scan and full Definition of Done gates pass.

## Out of scope

- TMS/LMS changes.
- External secret-manager integration.
- Multiple credentials or per-project service accounts.
