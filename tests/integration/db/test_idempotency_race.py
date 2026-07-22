"""CPS-105 Task 5: idempotent operation creation integration tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import PendingRollbackError

from cps.domain.operations.create import create_operation_idempotent
from cps.domain.operations.errors import IdempotencyConflictError
from cps.domain.operations.idempotency import canonical_fingerprint
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.operations import IdempotencyScopeConflictError
from cps.infrastructure.db.repositories.providers import (
    AddConnectionCommand,
    AddCredentialCommand,
    AddProviderCommand,
)
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.credentials import AesGcmCredentialCipher, MappingCredentialKeyProvider
from tests.integration.db.idempotency_test_support import (
    BarrierOperationRepository,
    IdempotencyRaceCoordinator,
)

pytestmark = pytest.mark.integration

_OPERATION_TYPE = "openstack.connection.validate"
_TEST_KEY = b"c" * 32
_KEY_VERSION = "v1"
_PLAINTEXT = "synthetic-test-password-value"  # pragma: allowlist secret


@pytest.fixture
def cipher() -> AesGcmCredentialCipher:
    return AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))


async def _seed_connection(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> tuple[uuid.UUID, uuid.UUID]:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    connection_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_provider(
            AddProviderCommand(provider_id=provider_id, name="provider-idempotency")
        )
        await uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username="service-user",
                encrypted_password=encrypted,
                encrypted_username=cipher.encrypt_secret(
                    credential_id=credential_id,
                    field_label="username",
                    plaintext="service-user",
                    key_version=_KEY_VERSION,
                ),
            )
        )
        await uow.providers.add_connection(
            AddConnectionCommand(
                connection_id=connection_id,
                provider_id=provider_id,
                credential_id=credential_id,
                project_name="demo",
                region_name="RegionOne",
                auth_url="https://keystone.example/v3",
            )
        )
        await uow.commit()
    return connection_id, provider_id


async def _create_operation(
    db_session_factory,
    *,
    connection_id: uuid.UUID,
    request_payload: dict,
    idempotency_key: str | None,
) -> Operation:
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        operation = await create_operation_idempotent(
            uow.operations,
            provider_connection_id=connection_id,
            operation_type=_OPERATION_TYPE,
            request_payload=request_payload,
            correlation_id=uuid.uuid4(),
            idempotency_key=idempotency_key,
        )
        await uow.commit()
        return operation


@pytest.mark.asyncio
async def test_same_key_same_payload_returns_existing_operation(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)
    payload = {"project": "demo", "region": "RegionOne"}

    first = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload=payload,
        idempotency_key="idem-same-payload",
    )
    second = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload={"region": "RegionOne", "project": "demo"},
        idempotency_key="idem-same-payload",
    )

    assert first.id == second.id
    assert first.request_fingerprint == second.request_fingerprint


@pytest.mark.asyncio
async def test_same_key_different_payload_raises_conflict(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)

    await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload={"action": "validate"},
        idempotency_key="idem-conflict",
    )

    with pytest.raises(IdempotencyConflictError):
        await _create_operation(
            db_session_factory,
            connection_id=connection_id,
            request_payload={"action": "create"},
            idempotency_key="idem-conflict",
        )


@pytest.mark.asyncio
async def test_missing_idempotency_key_always_creates_new_operation(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)
    payload = {"action": "validate"}

    first = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload=payload,
        idempotency_key=None,
    )
    second = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload=payload,
        idempotency_key=None,
    )

    assert first.id != second.id


@pytest.mark.asyncio
async def test_savepoint_recovery_allows_lookup_after_unique_violation(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)
    payload = {"action": "validate", "scope": "recovery"}
    idempotency_key = "idem-savepoint-recovery"
    winner = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload=payload,
        idempotency_key=idempotency_key,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        repository = uow.operations
        fingerprint = canonical_fingerprint(payload)
        with pytest.raises(IdempotencyScopeConflictError):
            await repository.insert_operation(
                operation_id=new_uuid7(),
                provider_connection_id=connection_id,
                operation_type=_OPERATION_TYPE,
                request_payload=payload,
                request_fingerprint=fingerprint,
                correlation_id=uuid.uuid4(),
                idempotency_key=idempotency_key,
            )

        recovered = await repository.get_by_idempotency_scope(
            provider_connection_id=connection_id,
            operation_type=_OPERATION_TYPE,
            idempotency_key=idempotency_key,
        )
        assert recovered is not None
        assert recovered.id == winner.id
        assert not uow.session.in_nested_transaction()


@pytest.mark.asyncio
async def test_outer_transaction_survives_idempotency_conflict_recovery(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, provider_id = await _seed_connection(db_session_factory, cipher)
    payload = {"action": "validate", "scope": "outer-tx"}
    idempotency_key = "idem-outer-tx"
    winner = await _create_operation(
        db_session_factory,
        connection_id=connection_id,
        request_payload=payload,
        idempotency_key=idempotency_key,
    )

    async with db_session_factory() as lookup_session:
        original_provider = await lookup_session.get(Provider, provider_id)
        assert original_provider is not None
        original_name = original_provider.name

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        provider = await uow.providers.get_provider(provider_id)
        assert provider is not None
        provider.name = "provider-updated-in-outer-tx"
        await uow.session.flush()

        repository = uow.operations
        fingerprint = canonical_fingerprint(payload)
        with pytest.raises(IdempotencyScopeConflictError):
            await repository.insert_operation(
                operation_id=new_uuid7(),
                provider_connection_id=connection_id,
                operation_type=_OPERATION_TYPE,
                request_payload=payload,
                request_fingerprint=fingerprint,
                correlation_id=uuid.uuid4(),
                idempotency_key=idempotency_key,
            )

        recovered = await repository.get_by_idempotency_scope(
            provider_connection_id=connection_id,
            operation_type=_OPERATION_TYPE,
            idempotency_key=idempotency_key,
        )
        assert recovered is not None
        assert recovered.id == winner.id
        await uow.commit()

    async with db_session_factory() as session:
        refreshed_provider = await session.get(Provider, provider_id)
        assert refreshed_provider is not None
        assert refreshed_provider.name == "provider-updated-in-outer-tx"
        assert refreshed_provider.name != original_name


@pytest.mark.asyncio
async def test_concurrent_identical_creates_produce_single_row(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)
    payload = {"action": "validate", "scope": "connection"}
    idempotency_key = "idem-race"
    coordinator = IdempotencyRaceCoordinator(worker_count=10)

    async def create_once() -> Operation:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            repository = BarrierOperationRepository(uow.operations, coordinator)
            operation = await create_operation_idempotent(
                repository,
                provider_connection_id=connection_id,
                operation_type=_OPERATION_TYPE,
                request_payload=payload,
                correlation_id=uuid.uuid4(),
                idempotency_key=idempotency_key,
            )
            await uow.commit()
            return operation

    results = await asyncio.gather(*(create_once() for _ in range(10)))
    assert len({operation.id for operation in results}) == 1
    assert coordinator.conflict_recoveries >= 1

    async with db_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Operation)
            .where(
                Operation.provider_connection_id == connection_id,
                Operation.idempotency_key == idempotency_key,
            )
        )
        assert count == 1


@pytest.mark.asyncio
async def test_concurrent_different_payloads_raise_conflict_and_keep_single_row(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    connection_id, _ = await _seed_connection(db_session_factory, cipher)
    idempotency_key = "idem-race-conflict"
    coordinator = IdempotencyRaceCoordinator(worker_count=2)
    first_payload = {"action": "validate", "variant": "first"}
    second_payload = {"action": "validate", "variant": "second"}

    async def create_with_payload(payload: dict) -> Operation | BaseException:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        try:
            async with uow:
                repository = BarrierOperationRepository(uow.operations, coordinator)
                operation = await create_operation_idempotent(
                    repository,
                    provider_connection_id=connection_id,
                    operation_type=_OPERATION_TYPE,
                    request_payload=payload,
                    correlation_id=uuid.uuid4(),
                    idempotency_key=idempotency_key,
                )
                await uow.commit()
                return operation
        except IdempotencyConflictError as exc:
            return exc

    first_result, second_result = await asyncio.gather(
        create_with_payload(first_payload),
        create_with_payload(second_payload),
    )

    successful_results = [
        result for result in (first_result, second_result) if isinstance(result, Operation)
    ]
    conflict_results = [
        result
        for result in (first_result, second_result)
        if isinstance(result, IdempotencyConflictError)
    ]

    assert len(successful_results) == 1
    assert len(conflict_results) == 1
    successful_result = successful_results[0]
    conflict_result = conflict_results[0]
    assert not isinstance(conflict_result, PendingRollbackError)
    assert coordinator.conflict_recoveries >= 1

    async with db_session_factory() as session:
        stored = await session.scalar(
            select(Operation).where(
                Operation.provider_connection_id == connection_id,
                Operation.idempotency_key == idempotency_key,
            )
        )
        assert stored is not None
        assert stored.id == successful_result.id
        assert stored.request_payload == successful_result.request_payload
        assert stored.request_fingerprint == canonical_fingerprint(
            successful_result.request_payload
        )
        count = await session.scalar(
            select(func.count())
            .select_from(Operation)
            .where(
                Operation.provider_connection_id == connection_id,
                Operation.idempotency_key == idempotency_key,
            )
        )
        assert count == 1
