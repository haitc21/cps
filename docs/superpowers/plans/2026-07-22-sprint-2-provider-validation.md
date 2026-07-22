# Sprint 2 Provider Validation Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the Cursor Composer 2.5 Fast worker for implementation and Codex for planning, verification, and review. Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and `superpowers:requesting-code-review` task-by-task. Cursor must not run git add, commit, push, reset, checkout, or restore.

**Goal:** Deliver CPS provider/credential/connection APIs and OPS read-only OpenStack validation through a durable, reference-only command and capability result.

**Architecture:** CPS owns public REST, encrypted credential persistence, operation/outbox/inbox transactions, canonical contracts, and capability status. OPS resolves one credential reference just-in-time, creates an in-memory OpenStackSDK connection, discovers safe service capabilities, and returns ordered progress plus terminal events. The existing RabbitMQ consumer publishes every event with confirms before one ACK; neither service persists OpenStack sessions or plaintext.

**Tech Stack:** CPython 3.12, FastAPI 0.139, Pydantic 2.13, SQLAlchemy 2.0 async, Alembic, PostgreSQL 18, aio-pika/RabbitMQ 4.1, OpenStackSDK 4.17, httpx, pytest/pytest-asyncio, Ruff, mypy, JSON Schema, Docker Compose.

## Global Constraints

- CPS and OPS remain independent repositories with remotes `git@github.com:haitc21/cps.git` and `git@github.com:haitc21/ops.git`.
- Use Ubuntu Bash, `uv`, forward-slash paths, CPython 3.12, and LF files; do not add Windows-only commands to active instructions.
- CPS never imports OpenStackSDK. OPS has no business database and never persists, caches, or logs plaintext credentials.
- CPS owns canonical schemas and fixtures; OPS copies them byte-for-byte and updates both manifests only from CPS.
- All CPS-created IDs are UUIDv7; all timestamps are UTC; API list ordering is allow-listed with ID tie-breakers.
- Public responses and messages exclude password, username where classified secret, ciphertext, nonce, key version, CA body, token, session, raw catalog, raw provider response, and credential reference in events.
- Every mutation uses optimistic `version`; every relevant mutation accepts `Idempotency-Key`; stable `CommonError` codes are required.
- Alembic revisions are immutable. Migration tests use a disposable PostgreSQL database and run upgrade→downgrade→upgrade.
- OpenStack validation uses authentication/catalog/version discovery and safe reads only. It creates, updates, or deletes no provider resource.
- Fast model identifier is `composer-2.5-fast`; fallback to `auto` is allowed only for an explicit Fast quota/rate/allowance error and must be reported as `CURSOR_MODEL_FALLBACK: Composer 2.5 Fast -> Auto`.
- Codex independently inspects every Cursor diff, runs focused and full gates, classifies P0–P3, and owns commits/pushes.
- Any P0/P1/P2 finding blocks commit. Three repeated root-cause failures trigger architecture reassessment before another repair.

## Current Map and Approved Decisions

The Sprint 1B handoff is closed and pushed. Reusable CPS seams are `SqlAlchemyUnitOfWork`,
`ProviderRepository`, `OperationRepository`, `create_operation_idempotent`, transactional outbox,
`EventInboxConsumer`, `OperationInboxHandler`, and `AesGcmCredentialCipher`. OPS seams are
`CommandConsumer`, `ConfirmedPublisher`, `build_default_registry`, `validate_command_envelope`,
and `normalize_openstack_exception`. Current `openstack.connection.validate` is a progress-only
stub.

The approved Sprint 2 decisions are:

1. The canonical scope field is `project_name`, matching the persisted connection model. The old
   synthetic fixture's `project_id` is replaced; no provider ID is invented.
2. Internal resolution is `GET /internal/v1/credentials/{credential_reference}?provider_connection_id=...`.
   The pair is checked against one enabled connection before decrypting.
3. Public and internal CPS listeners are separate FastAPI app factories. Hiding a route from
   OpenAPI is not an ingress boundary.
4. Both username and password are encrypted independently. A new migration adds encrypted username
   columns, `rotated_at`, and the reserved `CANCELLED` operation enum value; it never edits the
   applied Sprint 1B revision.
5. Validation request commits `ACCEPTED→QUEUED`, operation, and outbox atomically. Progress payloads
   carry allow-listed `RUNNING`/`WAITING_PROVIDER` state. Retryable provider outage leaves a
   connection `PENDING_VALIDATION`; authentication/authorization/reference failures set `INVALID`.
6. `HandlerSuccess` is extended with an ordered tuple of outbound events. `CommandConsumer` confirms
   each event before ACK and closes the channel with no ACK on any confirm failure.

## Readiness and Baseline Evidence (CP0)

| Capability | Required | Detected | Status | Action |
|---|---:|---|---|---|
| Ubuntu | 26.04 or approved compatible | Ubuntu 26.04 LTS | READY | none |
| Bash/UTF-8 | Bash, UTF-8 | Bash 5.3.9, UTF-8 | READY | none |
| Git/SSH | authenticated GitHub read/write | git 2.53.0; remotes authenticated | READY | none |
| Python/uv | CPython 3.12, uv | Python 3.12.13, uv 0.11.31 | READY | none |
| Docker | Engine + Compose | Docker 29.3.1, Compose 5.1.1 | READY | none |
| Codex | authenticated CLI | codex-cli 0.145.0 | READY | none |
| Cursor | authenticated Fast model | Composer 2.5 Fast smoke success | READY | no fallback |
| CodeGraph/RTK | indexed workspace and command wrapper | CodeGraph 1.2.0, RTK 0.43.0 | READY | CodeGraph-first |
| Shell tools | ShellCheck/shfmt | 0.11.0/3.13.1 | READY | none |
| Sprint 1B | stories and 12 tasks done | CPS/OPS docs mark Done; gates passed | READY | none |
| CPS/OPS sync | clean and upstream-aligned | clean, local SHA == origin | READY | none |
| Compose infra | PostgreSQL 18/RabbitMQ 4.1/Valkey 9.1 | healthy containers | READY | no volume deletion |
| OpenStack host route | controller hostname from host | VM-to-VM HTTP 200; host resolver entry pending | MANUAL BLOCKER | before CP12, user-approved host route or direct approved endpoint |

CP0 portability commit is already pushed: CPS `b05ea02`, OPS `89173ba`. It updates active Ubuntu
README instructions, keeps the existing Husky shell gate, normalizes baseline path separators, uses
a private temporary baseline, excludes only the root baseline from candidates, and tests lifecycle
failure/exit-code/redaction behavior. No tracked CPS/OPS PowerShell script exists to port; unrelated
legacy PowerShell is documented as out of scope.

## Task 1 / CP1 — Canonical contracts and validation API design

**Stories:** CPS-204, CPS-205, OPS-201..204. **Commit order:** CPS first, then OPS pin.

**Files:**

- Modify CPS `src/cps/contracts/fixtures/commands/connection_validate.json` to use `project_name` only if scope is present and payload `{"validation_mode":"SAFE_READ_ONLY"}`.
- Create CPS `src/cps/contracts/jsonschema/capability_document.schema.json` and `credential_resolution.schema.json`.
- Modify CPS operation progress/completed/failed fixtures and `src/cps/contracts/semantic.py` to validate state/capability/error safe subsets by message type.
- Create `tests/contract/test_connection_validation_contract.py` with major-version, size, forbidden-key, and additive-minor tests.
- Copy identical schema/fixture bytes to OPS `src/ops/contracts/{jsonschema,fixtures}` and add pin assertions.
- Update CPS `src/cps/contracts/checksums.json`, OPS `checksums.json`, and `cps_checksums.pinned.json` through the existing manifest writers only.
- Create/update both sprint specs and plans before feature implementation.

**Interfaces:**

- `CapabilityDocument.model_validate(value) -> CapabilityDocument` and `validate_capability_document(value) -> dict[str, Any]` reject unknown major versions, raw SDK values, >64 KiB serialized data, missing required service/feature keys, and forbidden secret keys.
- `CredentialResolution` has auth URL, username, password, user/project domains, project name, region, interface, verify TLS, and optional CA PEM; it is internal-only and never an event payload.
- `ValidationProgress` has `progress: int`, `state: RUNNING|WAITING_PROVIDER`, and bounded `message`.
- `ValidationCompleted` has `status: VALID` and one canonical capability document. `ValidationFailed` has only `CommonError`.

**TDD steps:**

- [ ] Write one failing test per invalid major version, missing required capability, oversized result, forbidden key, credential reference in event, and accepted additive minor field.
- [ ] Run `uv run pytest -q tests/contract/test_connection_validation_contract.py`; confirm failures are missing validators/schema, not import errors.
- [ ] Implement Pydantic/JSON Schema and semantic dispatch with explicit allow-lists.
- [ ] Run CPS contract tests and `uv run python -m cps.contracts.validate_contracts`.
- [ ] Copy bytes to OPS, run `uv run python -m ops.contracts.validate_contracts` and `uv run pytest -q tests/contract/test_pin_against_cps.py tests/contract/test_connection_validation_contract.py`.
- [ ] Codex compares `sha256sum` of every canonical/pinned artifact and reviews secret-bearing fields.
- [ ] Commit CPS `feat(contracts): define provider validation capability contract`, then OPS `chore(contracts): pin provider validation contract`.

## Task 2 / CP1 — CPS migration, encryption key ring, and API infrastructure

**Stories:** CPS-202 foundation. **Dependencies:** Task 1.

**Files:**

- Create `cps/alembic/versions/20260722_0002_sprint2_credentials.py` with encrypted username columns, `rotated_at`, and `CANCELLED` enum migration; add safe non-empty legacy guard and reversible empty-schema downgrade.
- Modify `cps/src/cps/infrastructure/db/models/credentials.py`, `operations.py`, `enums.py`, and `models/__init__.py` for new columns/value.
- Modify `cps/src/cps/security/credentials.py` with field-labeled `encrypt_secret`/`decrypt_secret` while preserving password compatibility and redacted representations.
- Modify `cps/src/cps/config.py` with active key version and parsed key-ring settings; invalid/missing keys fail closed without logging values.
- Create `cps/src/cps/api/dependencies.py`, `api/pagination.py`, `api/schemas/common.py`, and `application/services/transaction.py` for session/UoW injection, allow-listed paging, and one commit owner.
- Modify `cps/src/cps/main.py`, `cli.py`, and lifecycle helpers to create/dispose a public app and a separate internal app.
- Extend `cps/src/cps/observability/redaction.py` and tests to redact CA private material and all secret-bearing DTO fields.

**TDD steps:**

- [ ] Add migration lifecycle, model parity, key ring, field-AAD swap, wrong-key, missing-key, and CA-redaction failing tests.
- [ ] Run `CPS_RUN_INTEGRATION=1 uv run pytest -q tests/integration/db/test_migration_lifecycle.py tests/integration/db/test_schema_catalog.py tests/unit/security/test_credential_cipher.py tests/unit/test_redaction.py`; capture RED.
- [ ] Implement migration and crypto/config boundaries without plaintext backfill; non-empty legacy guard must return a safe operational error.
- [ ] Run migration upgrade→downgrade→upgrade on disposable PostgreSQL 18 and focused tests.
- [ ] Run `uv run ruff format --check src tests alembic`, `uv run ruff check src tests alembic`, and `uv run mypy`.
- [ ] Codex verifies no plaintext column/value is read into logs or public models and reviews downgrade behavior.
- [ ] Commit `feat(cps): add Sprint 2 encrypted credential foundation`.

## Task 3 / CP2 — CPS-201 provider CRUD

**Files:**

- Create `cps/src/cps/api/schemas/providers.py`, `api/routers/providers.py`, and `cps/src/cps/application/providers.py`.
- Modify `cps/src/cps/infrastructure/db/repositories/providers.py` with list/filter/update/disable methods and normalized integrity errors.
- Modify `cps/src/cps/main.py` to include only the public provider router.
- Create `cps/tests/unit/api/test_providers.py` and extend repository integration tests.

**Interfaces:**

- `ProviderService.create(command: CreateProviderCommand) -> ProviderView`.
- `ProviderService.list(query: ProviderListQuery) -> Page[ProviderView]`.
- `ProviderService.update(provider_id, expected_version, patch) -> ProviderView`.
- `ProviderRepository.update_provider(..., expected_version) -> Provider`, using `WHERE id AND version` and mapping zero rows to `ConcurrentUpdateError`.

**TDD steps:**

- [ ] Write failing TestClient tests for create/list/get/PATCH, OPENSTACK-only validation, page bounds/order, unknown ID, stale version, duplicate name policy, disable referenced provider, and public secret absence.
- [ ] Run `uv run pytest -q tests/unit/api/test_providers.py`; verify route/service failures are expected.
- [ ] Implement DTOs, service, repository query allow-lists, and `CommonError` mappings (`PROVIDER_NOT_FOUND`, `VERSION_CONFLICT`, `INVALID_REQUEST`).
- [ ] Run focused unit/repository tests, then `CPS_RUN_INTEGRATION=1 uv run pytest -q tests/integration/db/test_provider_repository.py`.
- [ ] Codex reviews transaction ownership, SQL ordering/tie-breaker, and no destructive delete.
- [ ] Commit `feat(cps): add provider CRUD API` and push after full CPS gates for the task.

## Task 4 / CP3 — CPS-202 encrypted credential lifecycle

**Files:**

- Create `cps/src/cps/api/schemas/credentials.py` and `api/routers/credentials.py`.
- Create `cps/src/cps/application/credentials.py` with create/update/rotate/delete metadata services.
- Extend `cps/src/cps/infrastructure/db/repositories/providers.py` or a focused `repositories/credentials.py` with reference-count checks and optimistic updates.
- Create `cps/tests/unit/api/test_credentials.py`, `tests/unit/application/test_credential_lifecycle.py`, and integration redaction/deletion tests.

**Interfaces:**

- `CredentialService.create(input: CredentialWrite) -> CredentialMetadataView`.
- `CredentialService.update(id, expected_version, input) -> CredentialMetadataView`.
- `CredentialService.delete(id) -> None`, raising `ResourceInUseError` when a connection FK exists.
- `CredentialResolutionService.resolve(connection_id, credential_id) -> CredentialResolution` remains internal and is consumed by Task 7.

**TDD steps:**

- [ ] Write failing tests for create/update/delete metadata, ciphertext-at-rest, username/password non-return, key rotation, wrong/missing key, referenced delete, stale version, log/fixture/error redaction, and internal-scope release.
- [ ] Run `uv run pytest -q tests/unit/api/test_credentials.py tests/unit/application/test_credential_lifecycle.py`; confirm RED.
- [ ] Implement field-bound AES-GCM with independent nonces and active-key rotation inside one UoW; never include plaintext in request fingerprint or exception notes.
- [ ] Run all focused tests plus disposable migration integration and secret scan against staged allowlist.
- [ ] Codex inspects database rows with a read-only query that asserts no plaintext username/password and checks public OpenAPI excludes internal resolver.
- [ ] Commit `feat(cps): add encrypted credential lifecycle` and push.

## Task 5 / CP4 — CPS-203 provider connection API

**Files:**

- Create `cps/src/cps/api/schemas/connections.py`, `api/routers/connections.py`, and `application/connections.py`.
- Extend `ProviderRepository` with connection list/update and explicit provider/credential status checks.
- Modify safe serializers and `tests/unit/api/test_provider_connections.py` plus DB constraints tests.

**Interfaces:**

- `ConnectionService.create(provider_id, input: ConnectionCreate) -> ConnectionView`.
- `ConnectionService.update(connection_id, expected_version, patch) -> ConnectionView`.
- `ConnectionView` contains no credential ID or CA PEM; `has_custom_ca` is boolean metadata.

**TDD steps:**

- [ ] Add failing tests for one project/domain/region identity, valid refs, default PENDING_VALIDATION, duplicate 409, disabled provider/credential rejection, TLS/interface/CA validation, PATCH version conflict, reset-to-pending on scope change, and no public secret.
- [ ] Run `uv run pytest -q tests/unit/api/test_provider_connections.py`; confirm missing route/service failures.
- [ ] Implement one-UoW create/update, unique constraint mapping, bounded URLs/CA size, and capability/error clearing on material changes.
- [ ] Run repository/database integration, migration parity, and contract tests.
- [ ] Codex checks FK restrict behavior and that no credential plaintext reaches `ConnectionView`.
- [ ] Commit `feat(cps): add provider connection API` and push.

## Task 6 / CP5 — CPS-206 operation query API

**Files:**

- Create `cps/src/cps/api/schemas/operations.py`, `api/routers/operations.py`, and `application/operations.py`.
- Extend `OperationRepository` with page queries and event page queries using allow-listed filters and stable ID tie-breakers.
- Extend safe event/result projection tests in `tests/unit/api/test_operations.py` and integration operation tests.

**Interfaces:**

- `OperationQueryService.list(query: OperationListQuery) -> Page[OperationView]`.
- `OperationQueryService.get(id) -> OperationView`.
- `OperationQueryService.events(id, page) -> Page[OperationEventView]` with `sequence ASC`.

**TDD steps:**

- [ ] Write failing tests for list/get/events, unknown 404, state/type/provider filters, offset/limit bounds, sort tie-breaker, terminal safe result/error, actor/trace/provider request ID preservation, and forbidden raw provider/secret keys.
- [ ] Run `uv run pytest -q tests/unit/api/test_operations.py`; capture expected RED.
- [ ] Implement repository queries, projection validator, page DTO, and error mapping.
- [ ] Run `CPS_RUN_INTEGRATION=1 uv run pytest -q tests/integration/db/test_operation_transitions.py tests/integration/db/test_idempotency_race.py`.
- [ ] Codex reviews query SQL, event immutability, and raw payload filtering.
- [ ] Commit `feat(cps): add operation query APIs` and push.

## Task 7 / CP6 — CPS-204 internal resolver

**Files:**

- Create `cps/src/cps/api/internal_app.py`, `api/internal_router.py`, `api/schemas/internal_credentials.py`, and `application/internal_credentials.py`.
- Modify `cps/src/cps/cli.py` with a separate `serve-internal` command and `cps/deploy/docker/README.md` with local-only binding instructions.
- Create `tests/unit/api/test_internal_credentials.py` and an OpenAPI exclusion test.

**Interfaces:**

- `resolve_credential(connection_id: UUID, credential_id: UUID) -> CredentialResolution`.
- `create_internal_app(settings=None) -> FastAPI`, with only health and `/internal/v1/credentials/{reference}`.

**TDD steps:**

- [ ] Write failing tests for valid pair resolution, mismatch/disabled/not-found, bounded response, no cache, no logs, missing key fail-closed, and public app/OpenAPI absence.
- [ ] Run `uv run pytest -q tests/unit/api/test_internal_credentials.py`; confirm RED.
- [ ] Implement separate app/router, network-boundary dependency hook, one handler-scope decrypt, generic error responses, and response-size guard.
- [ ] Run public/internal app route tests and `bash .husky/pre-commit` on an explicit staging allowlist.
- [ ] Codex reviews route exposure with `app.openapi()`, log capture, and plaintext lifetime.
- [ ] Commit `feat(cps): add internal credential resolution boundary` and push.

## Task 8 / CP7 — OPS-201 CPS credential resolver client

**Files:**

- Move `httpx` from OPS dev extras to runtime dependencies in `ops/pyproject.toml` and lock with `uv lock`.
- Create `ops/src/ops/application/credential_resolver.py` and tests `ops/tests/unit/application/test_credential_resolver.py`.
- Extend `ops/src/ops/config.py` with bounded CPS connect/read/write/pool timeout and response limit.

**Interfaces:**

- `CredentialResolver.resolve(credential_reference: UUID, provider_connection_id: UUID) -> CredentialResolution`.
- `CredentialResolver.close() -> Awaitable[None]`; handler uses `async with` or `try/finally` and never caches.

**TDD steps:**

- [ ] Write failing fake-httpx tests for exact URL/query, bounded timeout, valid response, malformed/oversized response, CPS 404/409 terminal mapping, timeout/5xx/network retryable mapping, client close, and no secret in logs/errors/events.
- [ ] Run `uv run pytest -q tests/unit/application/test_credential_resolver.py`; confirm RED.
- [ ] Implement one request per handler scope, JSON shape validation, max body check, redacted exception handling, and practical buffer release.
- [ ] Run `uv run ruff format --check src tests`, `uv run ruff check src tests`, `uv run mypy`, and focused tests.
- [ ] Codex inspects event/error serialization and caplog for username/password.
- [ ] Commit `feat(ops): add CPS credential resolver client` and push.

## Task 9 / CP8 — OPS-202 OpenStackSDK connection factory

**Files:**

- Create `ops/src/ops/openstack/connection_factory.py` and `ops/tests/unit/openstack/test_connection_factory.py`.
- Extend `ops/src/ops/config.py` for explicit user-agent, connect/read/total deadlines, and CA temp-file policy.

**Interfaces:**

- `OpenStackConnectionFactory.create(resolution: CredentialResolution) -> ConnectionHandle`.
- `ConnectionHandle.connection` is private to `ops/openstack`; `close()` removes CA material and releases the SDK session.

**TDD steps:**

- [ ] Write failing SDK-fake tests asserting auth URL, username/password, user/project domains, project name, region, interface, verify, CA path, timeout, app name/version, and no `clouds.yaml`/env loading.
- [ ] Add tests for invalid interface/URL, missing CA, CA file permissions/cleanup, SDK auth/network/timeout normalization, and no secret repr/log.
- [ ] Run `uv run pytest -q tests/unit/openstack/test_connection_factory.py -W error::DeprecationWarning`; confirm RED.
- [ ] Implement `openstack.connect(load_yaml_config=False, load_envvars=False, auth=..., region_name=..., interface=..., verify=..., cacert=..., api_timeout=..., app_name=..., app_version=...)` with bounded deadlines and no fixed release/microversion.
- [ ] Run focused tests with deprecations as errors and ruff/mypy.
- [ ] Codex inspects installed OpenStackSDK 4.17 call signature and verifies CA cleanup on all exceptions.
- [ ] Commit `feat(ops): add scoped OpenStackSDK connection factory` and push.

## Task 10 / CP9 — OPS-203 capability discovery and mapper

**Files:**

- Create `ops/src/ops/openstack/capabilities.py`, `ops/tests/unit/openstack/test_capabilities.py`, and capability fixtures.
- Extend `ops/src/ops/openstack/errors.py` only with safe request-ID/service context mappings required by the schema.

**Interfaces:**

- `CapabilityDiscoverer.discover(handle: ConnectionHandle) -> CapabilityDocument`.
- `normalize_service_catalog(...) -> ServiceCapability` and `normalize_version_data(...) -> VersionRange` return plain dict/model values only.

**TDD steps:**

- [ ] Write failing tests for Keystone authorize, catalog endpoint/version discovery, Nova/Neutron/Glance/Cinder availability, missing optional services, version-discovery errors, capability reasons, size bounds, and no raw SDK/token/catalog serialization.
- [ ] Run `uv run pytest -q tests/unit/openstack/test_capabilities.py`; confirm RED.
- [ ] Implement safe service probing and canonical schema validation; identity/compute are required, optional services become unsupported reasons.
- [ ] Run focused tests with `-W error::DeprecationWarning` and contract semantic validation.
- [ ] Codex compares mapper output byte-shape to CPS canonical schema and checks release/microversion assumptions.
- [ ] Commit `feat(ops): add OpenStack capability discovery` and push.

## Task 11 / CP9.5 — OPS multi-event confirm-before-ACK transport

**Files:**

- Modify `ops/src/ops/messaging/consumer.py` so `HandlerSuccess`/`HandlerFailedResult` carry an ordered tuple of outbound event messages while preserving a compatibility constructor for existing tests.
- Modify `ops/src/ops/application/dispatch.py` and registry types only as needed for the new outcome.
- Extend `ops/tests/unit/messaging/test_ack_policy.py`, `test_publisher.py`, and add ordered multi-event tests.

**Interfaces:**

- `OutboundEvent(routing_key: str, body: bytes)` is immutable.
- `_apply_outcome` publishes every `OutboundEvent` sequentially with `ConfirmedPublisher.publish`, then ACKs once; any confirm failure closes channel and returns incomplete.

**TDD steps:**

- [ ] Add failing tests for progress-confirm→terminal-confirm→ACK order, no ACK after either confirm failure, channel close, retry/redelivery, and single-event backward compatibility.
- [ ] Run `uv run pytest -q tests/unit/messaging/test_ack_policy.py tests/unit/messaging/test_publisher.py`; verify RED.
- [ ] Implement ordered publish loop without allowing handler-side publisher bypass.
- [ ] Run all OPS messaging tests and integration ACK/confirm tests against disposable RabbitMQ.
- [ ] Codex checks no code path ACKs before every confirm and no secret-bearing body is emitted.
- [ ] Commit `feat(ops): support confirmed multi-event handler outcomes` and push.

## Task 12 / CP10 — OPS-204 validation handler and runtime wiring

**Files:**

- Create `ops/src/ops/application/handlers/connection_validate.py` and `ops/tests/unit/application/test_connection_validate.py`.
- Modify `ops/src/ops/application/dispatch.py`, `messaging/runtime.py`, and handler registry wiring to inject resolver/factory/discoverer/settings.
- Replace `stub_connection_validate.py` registration only after focused handler tests pass; retain compatibility tests until removal is reviewed.

**Interfaces:**

- `ConnectionValidationHandler.handle(command: MessageEnvelope, metadata: DeliveryMetadata, routing_key: str) -> HandlerSuccess|HandlerFailedResult|HandlerRetryableError`.
- It returns deterministic `validation.started`/`validation.discovery`/terminal `OutboundEvent`s, with `credential_reference` omitted from all event envelopes.

**TDD steps:**

- [ ] Add failing tests for resolver→factory→discoverer call order, safe progress/terminal shapes, deterministic replay IDs, auth failure terminal result, unavailable/timeout retry result, optional service absence, malformed command rejection before resolver, and secret absence from body/log/error.
- [ ] Run `uv run pytest -q tests/unit/application/test_connection_validate.py tests/unit/application/test_dispatch.py`; capture RED.
- [ ] Implement handler with read-only discovery, total deadline, deterministic message IDs, normalized errors, and no provider mutations.
- [ ] Run focused tests, multi-event ACK tests, `-W error::DeprecationWarning` SDK tests, and RabbitMQ dispatch integration.
- [ ] Codex reviews retry/DLQ classification and replay behavior using a fake that fails after the first read.
- [ ] Commit `feat(ops): implement OpenStack connection validation handler` and push.

## Task 13 / CP11 — CPS-205 async validation endpoint and inbox persistence

**Files:**

- Create `cps/src/cps/api/schemas/validation.py`, `api/routers/validation.py`, and `application/validation.py`.
- Modify `cps/src/cps/domain/operations/create.py`, `service.py`, `inbox_handler.py`, and operation repositories for `ACCEPTED→QUEUED`, progress state, safe terminal error, and connection capability/status updates.
- Add `update_provider_connection_validation(...)` to a focused repository method with optimistic lock and status policy.
- Modify command/event semantic validators and tests in `tests/unit/operations`, `tests/unit/messaging`, `tests/integration/messaging`, and `tests/integration/db`.

**Interfaces:**

- `ValidationService.request(connection_id, idempotency_key, correlation_id) -> OperationView` creates operation+QUEUED event+reference-only outbox atomically.
- `OperationInboxHandler` validates `openstack.connection.validate` events and invokes one transaction owner for operation plus connection updates.
- `ProviderConnectionRepository.apply_validation_success/failure(...)` persists capabilities or safe error with status policy and version guard.

**TDD steps:**

- [ ] Write failing TestClient tests for HTTP 202, idempotent duplicate, conflicting idempotency, disabled/invalid connection, command reference-only payload, one outbox row, and correlation header.
- [ ] Write failing inbox integration tests for progress state transitions, capability success, auth failure INVALID, transient failure PENDING_VALIDATION, duplicate event, late event, ownership mismatch, malformed capability, and no secret in DB/event/log.
- [ ] Run focused CPS API/operation/messaging tests with disposable PostgreSQL/RabbitMQ; capture RED.
- [ ] Implement one UoW transaction and explicit safe validators; update inbox dedupe before ACK.
- [ ] Run `CPS_RUN_INTEGRATION=1 uv run pytest -q tests/integration/db tests/integration/messaging` and contract validation.
- [ ] Codex checks operation+connection+inbox atomicity under rollback and replay; no provider response is persisted.
- [ ] Commit `feat(cps): implement async provider connection validation workflow` and push.

## Task 14 / CP12 — Cross-repo integration and real OpenStack acceptance

**Files:**

- Create CPS `tests/e2e/test_provider_validation.py` and OPS `tests/integration/test_provider_validation_path.py` with safe environment guards.
- Add non-secret evidence writer under `docs/evidence/sprint-2/` only; never write `.env`, password, token, or raw HTTP body.
- Update Compose/readme only for existing local bindings; do not expose ports or delete volumes.

**Synthetic integration steps:**

- [ ] Start existing infra with `docker compose -f cps/deploy/docker/docker-compose.yml up -d --wait`.
- [ ] Run public CPS API + separate internal app + OPS worker with `CPS_RUN_INTEGRATION=1` and `OPS_RUN_INTEGRATION=1` against fake OpenStack HTTP/SDK fixtures.
- [ ] Assert 202→outbox reference→resolver→factory→safe discovery→progress/terminal confirms→CPS inbox→capabilities and operation query.
- [ ] Replay the same idempotency key and assert one operation and no second provider call.

**Real lab steps (only when host route/config is supplied):**

- [ ] Verify, without printing secrets, `getent hosts controller`, TCP 5000 reachability, `curl http://controller:5000/v3`, and Keystone auth with a temporary shell environment.
- [ ] Start the product path using `CPS_AUTH_URL`, `CPS_USERNAME`, `CPS_PASSWORD`, `CPS_USER_DOMAIN`, `CPS_PROJECT_DOMAIN`, `CPS_PROJECT_NAME`, `CPS_REGION`, and TLS/CA settings only in ignored runtime config.
- [ ] Create provider, encrypted credential, and one connection through CPS API; trigger validation with one idempotency key.
- [ ] Observe OPS resolver/factory/discovery and CPS operation/capability result. Query operation and event history.
- [ ] Repeat the key; assert same operation and no second concurrent operation/provider mutation.
- [ ] Optionally use a synthetic invalid password only if it does not modify OpenStack; assert safe authentication failure.
- [ ] Scan CPS/OPS logs, DB JSON, RabbitMQ payloads, HTTP responses, and pytest output for password/token/ciphertext/CA body.
- [ ] Do not create/update/delete VM, network, volume, image, project, user, or other OpenStack resources.

If host DNS/routing or required variables are unavailable, record `BLOCKED` with variable names and
the non-secret connectivity evidence; do not mark Sprint 2 Done.

## Task 15 / CP13 — Closure, independent review, and evidence

**Files:**

- Update `cps/plan/sprints/sprint-2.md`, `ops/plan/sprints/sprint-2.md`, canonical plan evidence, and review/retrospective sections.
- Create no Sprint 3 files and do not modify inventory/VM backlog status.

**Fresh verification commands:**

```bash
cd cps
uv lock --check
uv sync --frozen --all-extras
uv run ruff format --check src tests alembic
uv run ruff check src tests alembic
uv run mypy
uv run pytest -q
CPS_RUN_INTEGRATION=1 uv run pytest -q
uv run python -m cps.contracts.validate_contracts
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
git diff --check
bash .husky/pre-commit
docker build -t cps:sprint2 .
```

```bash
cd ops
uv lock --check
uv sync --frozen --all-extras
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
OPS_RUN_INTEGRATION=1 uv run pytest -q
uv run python -m ops.contracts.validate_contracts
uv run python -m pytest -q tests/unit/openstack -W error::DeprecationWarning
git diff --check
bash .husky/pre-commit
docker build -t ops:sprint2 .
```

- [ ] Hash `.secrets.baseline` before/after and assert unchanged except the reviewed path-normalization commit already in CP0.
- [ ] Run independent Codex final review over both diffs and CodeGraph blast radius; no P0–P3 remains.
- [ ] Record task commit SHAs, fresh counts, pre-commit exits, contract checksum, migration, Docker, and E2E evidence without secrets.
- [ ] Mark stories Done only after evidence; commit docs separately as `docs(sprint-2): record provider validation closure`.
- [ ] Push CPS and OPS with `git push origin HEAD`; verify local HEAD equals upstream and both worktrees/staged indexes are empty.
- [ ] Print `OK — Sprint 2 đã hoàn thành và được push` only if the real OpenStack acceptance succeeded. Otherwise print `BLOCKED`/`NOT_OK` with exact non-secret gate evidence and stop before Sprint 3.

## Definition of Done

All ten Sprint 2 stories have pushed story commits; CP0–CP13 evidence is fresh; canonical contracts
are byte-identical and pinned; migrations pass upgrade/downgrade/upgrade; CPS/OPS unit and
integration gates, Docker builds, ShellCheck, and Husky pass; no P0–P3 review findings remain; the
real OpenStack validation path succeeds with no secret leakage; both repositories are clean and
synchronized with origin; no inventory or VM lifecycle work is started.
