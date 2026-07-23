"""Durable CPS recovery jobs that never perform provider I/O."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cps.domain.operations.service import EVENT_TYPE_STATE_CHANGED
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.observability.metrics import metrics


async def timeout_expired_operations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    """Implementation entrypoint used by runtime and integration tests."""
    current = now or datetime.now(UTC)
    count = 0
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        operations = await uow.operations.list_expired_nonterminal(now=current, limit=batch_size)
        for operation in operations:
            await uow.operations.apply_terminal_failure(
                operation=operation,
                expected_version=operation.version,
                error_payload={
                    "code": "OPERATION_TIMEOUT",
                    "message": "Operation exceeded its deadline",
                    "category": "TIMEOUT",
                    "retryable": False,
                    "occurred_at": current.isoformat(),
                },
                event_id=uuid.uuid4(),
                event_type=EVENT_TYPE_STATE_CHANGED,
                message_id=None,
                from_state=operation.state,
                to_state=OperationState.TIMED_OUT,
            )
            count += 1
        await uow.commit()
        if count:
            metrics.increment("cps_operations_timed_out_total", count)
    return count
