"""Synchronization helpers for deterministic idempotency integration tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.repositories.operations import (
    IdempotencyScopeConflictError,
    OperationRepository,
)


@dataclass
class IdempotencyRaceCoordinator:
    """Coordinate worker lookups and inserts for deterministic race tests."""

    worker_count: int
    lookup_barrier: asyncio.Barrier = field(init=False)
    insert_barrier: asyncio.Barrier = field(init=False)
    conflict_recoveries: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self.lookup_barrier = asyncio.Barrier(self.worker_count)
        self.insert_barrier = asyncio.Barrier(self.worker_count)

    async def wait_after_initial_none_lookup(self) -> None:
        await self.lookup_barrier.wait()

    async def wait_before_insert(self) -> None:
        await self.insert_barrier.wait()

    async def record_conflict_recovery(self) -> None:
        async with self._lock:
            self.conflict_recoveries += 1


class BarrierOperationRepository:
    """Repository wrapper that synchronizes the first lookup and insert phases."""

    def __init__(
        self,
        inner: OperationRepository,
        coordinator: IdempotencyRaceCoordinator,
    ) -> None:
        self._inner = inner
        self._coordinator = coordinator
        self._skip_next_lookup_barrier = False

    async def get_by_idempotency_scope(
        self,
        *,
        provider_connection_id,
        operation_type: str,
        idempotency_key: str,
    ) -> Operation | None:
        skip_barrier = self._skip_next_lookup_barrier
        self._skip_next_lookup_barrier = False
        result = await self._inner.get_by_idempotency_scope(
            provider_connection_id=provider_connection_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
        )
        if not skip_barrier and result is None:
            await self._coordinator.wait_after_initial_none_lookup()
        return result

    async def insert_operation(self, **kwargs: Any) -> Operation:
        await self._coordinator.wait_before_insert()
        try:
            return await self._inner.insert_operation(**kwargs)
        except IdempotencyScopeConflictError:
            self._skip_next_lookup_barrier = True
            await self._coordinator.record_conflict_recovery()
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
