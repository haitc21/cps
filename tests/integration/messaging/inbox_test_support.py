"""Synchronization helpers for deterministic inbox dedupe integration tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cps.contracts.messages.envelope import MessageEnvelope
from cps.domain.messaging.inbox import InboxInsertResult, InboxReceiveDraft
from cps.domain.operations.inbox_handler import OperationInboxHandler
from cps.infrastructure.db.repositories.inbox import InboxRepository
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


@dataclass
class InboxRaceCoordinator:
    """Coordinate concurrent inbox inserts for deterministic race tests."""

    worker_count: int
    insert_barrier: asyncio.Barrier = field(init=False)
    after_insert_barrier: asyncio.Barrier = field(init=False)

    def __post_init__(self) -> None:
        self.insert_barrier = asyncio.Barrier(self.worker_count)
        self.after_insert_barrier = asyncio.Barrier(self.worker_count)

    async def wait_before_insert(self) -> None:
        await self.insert_barrier.wait()

    async def wait_after_insert(self) -> None:
        await self.after_insert_barrier.wait()


async def race_process_message(
    *,
    db_session_factory,
    coordinator: InboxRaceCoordinator,
    draft: InboxReceiveDraft,
    fixture: dict[str, Any],
    should_fail: bool,
) -> str:
    outcome = "unknown"
    try:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await coordinator.wait_before_insert()
            result = await uow.inbox.try_insert_received(draft)
            if result.is_duplicate:
                outcome = "duplicate"
                return outcome
            if should_fail:
                raise RuntimeError("handler failed")
            handler = OperationInboxHandler(uow.operations)
            await handler.handle(MessageEnvelope.model_validate(fixture))
            assert result.inbox_id is not None
            await uow.inbox.mark_processed(result.inbox_id, now=datetime.now(UTC))
            await uow.commit()
            outcome = "processed"
            return outcome
    except RuntimeError:
        outcome = "rolled_back"
        return outcome
    finally:
        await coordinator.wait_after_insert()


class BarrierInboxRepository:
    """Repository wrapper retained for unit tests of barrier helpers."""

    def __init__(
        self,
        inner: InboxRepository,
        coordinator: InboxRaceCoordinator,
        *,
        fail_after_insert: bool = False,
    ) -> None:
        self._inner = inner
        self._coordinator = coordinator
        self._fail_after_insert = fail_after_insert

    async def try_insert_received(self, draft: InboxReceiveDraft) -> InboxInsertResult:
        await self._coordinator.wait_before_insert()
        result = await self._inner.try_insert_received(draft)
        if result.requires_processing and self._fail_after_insert:
            await self._coordinator.wait_after_insert()
            msg = "simulated handler failure"
            raise RuntimeError(msg)
        await self._coordinator.wait_after_insert()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
