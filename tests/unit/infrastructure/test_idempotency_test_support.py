"""Unit tests for idempotency race test synchronization helpers."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from cps.infrastructure.db.repositories.operations import IdempotencyScopeConflictError
from tests.integration.db.idempotency_test_support import (
    BarrierOperationRepository,
    IdempotencyRaceCoordinator,
)

_BARRIER_TIMEOUT_SECONDS = 0.5


@pytest.fixture
def coordinator() -> IdempotencyRaceCoordinator:
    return IdempotencyRaceCoordinator(worker_count=1)


@pytest.fixture
def inner() -> AsyncMock:
    mock = AsyncMock()
    mock.get_by_idempotency_scope.return_value = None
    return mock


@pytest.fixture
def repository(
    inner: AsyncMock, coordinator: IdempotencyRaceCoordinator
) -> BarrierOperationRepository:
    return BarrierOperationRepository(inner, coordinator)


@pytest.mark.asyncio
async def test_initial_none_lookup_waits_on_barrier(
    repository: BarrierOperationRepository,
    coordinator: IdempotencyRaceCoordinator,
) -> None:
    coordinator.wait_after_initial_none_lookup = AsyncMock()

    await asyncio.wait_for(
        repository.get_by_idempotency_scope(
            provider_connection_id=uuid.uuid4(),
            operation_type="openstack.connection.validate",
            idempotency_key="lookup-1",
        ),
        timeout=_BARRIER_TIMEOUT_SECONDS,
    )

    coordinator.wait_after_initial_none_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_lookup_skips_barrier_once(
    repository: BarrierOperationRepository,
    coordinator: IdempotencyRaceCoordinator,
    inner: AsyncMock,
) -> None:
    repository._skip_next_lookup_barrier = True
    coordinator.wait_after_initial_none_lookup = AsyncMock()

    await repository.get_by_idempotency_scope(
        provider_connection_id=uuid.uuid4(),
        operation_type="openstack.connection.validate",
        idempotency_key="lookup-recovery",
    )

    coordinator.wait_after_initial_none_lookup.assert_not_awaited()
    assert repository._skip_next_lookup_barrier is False


@pytest.mark.asyncio
async def test_lookup_after_recovery_returns_to_barrier_behavior(
    repository: BarrierOperationRepository,
    coordinator: IdempotencyRaceCoordinator,
) -> None:
    repository._skip_next_lookup_barrier = True
    coordinator.wait_after_initial_none_lookup = AsyncMock()

    await repository.get_by_idempotency_scope(
        provider_connection_id=uuid.uuid4(),
        operation_type="openstack.connection.validate",
        idempotency_key="lookup-recovery",
    )
    await repository.get_by_idempotency_scope(
        provider_connection_id=uuid.uuid4(),
        operation_type="openstack.connection.validate",
        idempotency_key="lookup-normal",
    )

    coordinator.wait_after_initial_none_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_recovery_lookup_resets_barrier_skip_flag(
    repository: BarrierOperationRepository,
    coordinator: IdempotencyRaceCoordinator,
    inner: AsyncMock,
) -> None:
    repository._skip_next_lookup_barrier = True
    inner.get_by_idempotency_scope.side_effect = RuntimeError("lookup failed")
    coordinator.wait_after_initial_none_lookup = AsyncMock()

    with pytest.raises(RuntimeError, match="lookup failed"):
        await repository.get_by_idempotency_scope(
            provider_connection_id=uuid.uuid4(),
            operation_type="openstack.connection.validate",
            idempotency_key="lookup-failed",
        )

    assert repository._skip_next_lookup_barrier is False
    inner.get_by_idempotency_scope.side_effect = None
    inner.get_by_idempotency_scope.return_value = None

    await repository.get_by_idempotency_scope(
        provider_connection_id=uuid.uuid4(),
        operation_type="openstack.connection.validate",
        idempotency_key="lookup-after-failure",
    )

    coordinator.wait_after_initial_none_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_insert_conflict_sets_single_recovery_barrier_skip(
    repository: BarrierOperationRepository,
    inner: AsyncMock,
    coordinator: IdempotencyRaceCoordinator,
) -> None:
    inner.insert_operation.side_effect = IdempotencyScopeConflictError(
        "idempotency scope already exists"
    )
    coordinator.wait_before_insert = AsyncMock()
    coordinator.record_conflict_recovery = AsyncMock()

    with pytest.raises(IdempotencyScopeConflictError):
        await repository.insert_operation(operation_id=uuid.uuid4())

    assert repository._skip_next_lookup_barrier is True
    coordinator.record_conflict_recovery.assert_awaited_once()
