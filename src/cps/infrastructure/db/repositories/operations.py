"""Operation persistence repositories."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cps.domain.operations.errors import ConcurrentUpdateError, OperationPersistenceError
from cps.domain.operations.event_details import (
    SafeEventDetails,
    materialize_event_details,
    validate_event_details,
)
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.provider_connections import ProviderConnection

_OPERATION_EVENT_SEQUENCE_CONSTRAINT = "uq_operation_events_operation_sequence"
_OPERATIONS_IDEMPOTENCY_CONSTRAINT = "uq_operations_idempotency"


class IdempotencyScopeConflictError(Exception):
    """Raised when an idempotency scope insert races with a concurrent creator."""


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

    async def get_by_idempotency_scope(
        self,
        *,
        provider_connection_id: uuid.UUID,
        operation_type: str,
        idempotency_key: str,
    ) -> Operation | None:
        result = await self._session.execute(
            select(Operation).where(
                Operation.provider_connection_id == provider_connection_id,
                Operation.operation_type == operation_type,
                Operation.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def insert_operation(
        self,
        *,
        operation_id: uuid.UUID,
        provider_connection_id: uuid.UUID,
        operation_type: str,
        request_payload: dict[str, Any],
        request_fingerprint: str,
        correlation_id: uuid.UUID,
        idempotency_key: str | None = None,
        causation_id: uuid.UUID | None = None,
        actor_context: dict[str, Any] | None = None,
        timeout_at: datetime | None = None,
    ) -> Operation:
        operation = Operation(
            id=operation_id,
            provider_connection_id=provider_connection_id,
            operation_type=operation_type,
            state=OperationState.ACCEPTED,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            request_payload=request_payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_context=actor_context,
            timeout_at=timeout_at,
            version=1,
        )
        async with self._session.begin_nested():
            self._session.add(operation)
            await self._flush_or_raise()
        return operation

    async def get_provider_connection(
        self,
        connection_id: uuid.UUID,
    ) -> ProviderConnection | None:
        result = await self._session.execute(
            select(ProviderConnection).where(ProviderConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def apply_connection_validation(
        self,
        connection_id: uuid.UUID,
        *,
        capabilities: dict[str, Any] | None = None,
        validation_error: dict[str, Any] | None = None,
        valid: bool,
        pending: bool = False,
    ) -> None:
        from cps.infrastructure.db.models.enums import ConnectionStatus

        if pending:
            status = ConnectionStatus.PENDING_VALIDATION
        else:
            status = ConnectionStatus.VALID if valid else ConnectionStatus.INVALID
        result = await self._session.execute(
            update(ProviderConnection)
            .where(ProviderConnection.id == connection_id)
            .values(
                status=status,
                capabilities=capabilities,
                validation_error=validation_error,
                validated_at=datetime.now(UTC),
            )
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise OperationPersistenceError("provider connection not found")

    async def get_events(self, operation_id: uuid.UUID) -> list[OperationEvent]:
        result = await self._session.execute(
            select(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
            .order_by(OperationEvent.sequence)
        )
        return list(result.scalars().all())

    async def list_operations(
        self,
        *,
        offset: int,
        limit: int,
        provider_connection_id: uuid.UUID | None = None,
        operation_type: str | None = None,
        state: OperationState | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[Operation], int]:
        filters = []
        if provider_connection_id is not None:
            filters.append(Operation.provider_connection_id == provider_connection_id)
        if operation_type is not None:
            filters.append(Operation.operation_type == operation_type)
        if state is not None:
            filters.append(Operation.state == state)
        if created_from is not None:
            filters.append(Operation.created_at >= created_from)
        if created_to is not None:
            filters.append(Operation.created_at <= created_to)
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(Operation).where(*filters)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(Operation)
            .where(*filters)
            .order_by(Operation.created_at, Operation.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

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

    async def apply_terminal_completion(
        self,
        *,
        operation: Operation,
        expected_version: int,
        result_payload: dict[str, Any],
        event_id: uuid.UUID,
        event_type: str,
        message_id: uuid.UUID | None,
        from_state: OperationState,
        to_state: OperationState,
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
            details=materialize_event_details(validate_event_details({"result": result_payload})),
        )
        self._session.add(event)
        await self._update_operation(
            operation_id=operation.id,
            expected_version=expected_version,
            values={
                "state": to_state,
                "result_payload": copy.deepcopy(result_payload),
            },
        )
        await self._flush_or_raise()
        refreshed = await self.get_operation(operation.id)
        if refreshed is None:
            msg = "operation not found"
            raise OperationPersistenceError(msg)
        return refreshed

    async def apply_terminal_failure(
        self,
        *,
        operation: Operation,
        expected_version: int,
        error_payload: dict[str, Any],
        event_id: uuid.UUID,
        event_type: str,
        message_id: uuid.UUID | None,
        from_state: OperationState,
        to_state: OperationState,
        provider_request_id: str | None = None,
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
            details=materialize_event_details(
                validate_event_details({"error_code": error_payload.get("code")})
            ),
        )
        self._session.add(event)
        values: dict[str, Any] = {
            "state": to_state,
            "error_payload": copy.deepcopy(error_payload),
        }
        if provider_request_id is not None:
            values["provider_request_id"] = provider_request_id
        await self._update_operation(
            operation_id=operation.id,
            expected_version=expected_version,
            values=values,
        )
        await self._flush_or_raise()
        refreshed = await self.get_operation(operation.id)
        if refreshed is None:
            msg = "operation not found"
            raise OperationPersistenceError(msg)
        return refreshed

    async def apply_late_result(
        self,
        *,
        operation: Operation,
        event_id: uuid.UUID,
        event_type: str,
        message_id: uuid.UUID | None,
        details: SafeEventDetails,
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
        if constraint_name == _OPERATIONS_IDEMPOTENCY_CONSTRAINT:
            msg = "idempotency scope already exists"
            raise IdempotencyScopeConflictError(msg) from None
        msg = "operation persistence failed"
        raise OperationPersistenceError(msg) from None
    msg = "operation persistence failed"
    raise OperationPersistenceError(msg) from None
