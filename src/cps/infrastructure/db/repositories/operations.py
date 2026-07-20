"""Operation persistence repositories."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cps.domain.operations.errors import ConcurrentUpdateError, OperationPersistenceError
from cps.domain.operations.event_details import SafeEventDetails, materialize_event_details
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation

_OPERATION_EVENT_SEQUENCE_CONSTRAINT = "uq_operation_events_operation_sequence"


class OperationRepository:
    """Async repository for operation state and immutable event history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_operation(self, operation_id: uuid.UUID) -> Operation | None:
        result = await self._session.execute(
            select(Operation).where(Operation.id == operation_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_operation(self, operation_id: uuid.UUID) -> Operation | None:
        result = await self._session.execute(select(Operation).where(Operation.id == operation_id))
        return result.scalar_one_or_none()

    async def get_events(self, operation_id: uuid.UUID) -> list[OperationEvent]:
        result = await self._session.execute(
            select(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
            .order_by(OperationEvent.sequence)
        )
        return list(result.scalars().all())

    async def apply_state_transition(
        self,
        *,
        operation: Operation,
        expected_version: int,
        to_state: OperationState,
        event_id: uuid.UUID,
        event_type: str,
        details: SafeEventDetails,
        message_id: uuid.UUID | None,
        from_state: OperationState,
    ) -> Operation:
        sequence = await self._next_sequence(operation.id)
        event = OperationEvent(
            id=event_id,
            operation_id=operation.id,
            sequence=sequence,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            message_id=message_id,
            details=materialize_event_details(details),
        )
        self._session.add(event)
        await self._update_operation(
            operation_id=operation.id,
            expected_version=expected_version,
            values={
                "state": to_state,
            },
        )
        await self._flush_or_raise()
        refreshed = await self.get_operation(operation.id)
        if refreshed is None:
            msg = "operation not found"
            raise OperationPersistenceError(msg)
        return refreshed

    async def apply_progress_update(
        self,
        *,
        operation: Operation,
        expected_version: int,
        progress_percent: int,
        event_id: uuid.UUID,
        event_type: str,
        details: SafeEventDetails,
        message_id: uuid.UUID | None,
    ) -> Operation:
        sequence = await self._next_sequence(operation.id)
        event = OperationEvent(
            id=event_id,
            operation_id=operation.id,
            sequence=sequence,
            event_type=event_type,
            from_state=None,
            to_state=None,
            message_id=message_id,
            details=materialize_event_details(details),
        )
        self._session.add(event)
        await self._update_operation(
            operation_id=operation.id,
            expected_version=expected_version,
            values={
                "progress_percent": progress_percent,
            },
        )
        await self._flush_or_raise()
        refreshed = await self.get_operation(operation.id)
        if refreshed is None:
            msg = "operation not found"
            raise OperationPersistenceError(msg)
        return refreshed

    async def _next_sequence(self, operation_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(OperationEvent.sequence), 0)).where(
                OperationEvent.operation_id == operation_id
            )
        )
        return int(result.scalar_one()) + 1

    async def _update_operation(
        self,
        *,
        operation_id: uuid.UUID,
        expected_version: int,
        values: dict[str, Any],
    ) -> None:
        update_values = {
            **values,
            "version": Operation.version + 1,
            "updated_at": func.now(),
        }
        result = await self._session.execute(
            update(Operation)
            .where(
                Operation.id == operation_id,
                Operation.version == expected_version,
            )
            .values(**update_values)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            msg = "concurrent update detected"
            raise ConcurrentUpdateError(msg)

    async def _flush_or_raise(self) -> None:
        database_error: DBAPIError | None = None
        try:
            await self._session.flush()
        except DBAPIError as exc:
            database_error = exc
        if database_error is not None:
            _raise_from_database_error(database_error)


def _extract_constraint_name(exc: DBAPIError) -> str | None:
    orig = exc.orig
    if orig is None:
        return None
    diag = getattr(orig, "diag", None)
    if diag is None:
        return None
    return getattr(diag, "constraint_name", None)


def _raise_from_database_error(exc: DBAPIError) -> None:
    if isinstance(exc, IntegrityError):
        constraint_name = _extract_constraint_name(exc)
        if constraint_name == _OPERATION_EVENT_SEQUENCE_CONSTRAINT:
            msg = "concurrent update detected"
            raise ConcurrentUpdateError(msg)
        msg = "operation persistence failed"
        raise OperationPersistenceError(msg)
    msg = "operation persistence failed"
    raise OperationPersistenceError(msg)
