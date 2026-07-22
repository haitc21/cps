"""Operation state machine domain service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from cps.domain.operations.errors import (
    ConcurrentUpdateError,
    InvalidProgressStateError,
    OperationNotFoundError,
)
from cps.domain.operations.event_details import validate_event_details
from cps.domain.operations.progress import validate_progress_percent
from cps.domain.operations.transitions import validate_transition
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.operations import Operation

if TYPE_CHECKING:
    from cps.infrastructure.db.repositories.operations import OperationRepository

EVENT_TYPE_STATE_CHANGED = "STATE_CHANGED"
EVENT_TYPE_PROGRESS = "PROGRESS"
EVENT_TYPE_LATE_RESULT = "LATE_RESULT"

PROGRESS_ALLOWED_STATES = frozenset(
    {
        OperationState.RUNNING,
        OperationState.WAITING_PROVIDER,
    }
)


class OperationService:
    """Domain service for operation transitions and progress history."""

    def __init__(self, repository: OperationRepository) -> None:
        self._repository = repository

    async def transition_operation(
        self,
        *,
        operation_id: uuid.UUID,
        expected_version: int,
        to_state: OperationState,
        details: dict[str, Any] | None = None,
        message_id: uuid.UUID | None = None,
    ) -> Operation:
        safe_details = validate_event_details(details)
        operation = await self._repository.lock_operation(operation_id)
        if operation is None:
            msg = "operation not found"
            raise OperationNotFoundError(msg)
        if operation.version != expected_version:
            msg = "concurrent update detected"
            raise ConcurrentUpdateError(msg)
        validate_transition(operation.state, to_state)
        return await self._repository.apply_state_transition(
            operation=operation,
            expected_version=expected_version,
            to_state=to_state,
            event_id=new_uuid7(),
            event_type=EVENT_TYPE_STATE_CHANGED,
            details=safe_details,
            message_id=message_id,
            from_state=operation.state,
        )

    async def record_progress(
        self,
        *,
        operation_id: uuid.UUID,
        expected_version: int,
        progress_percent: int,
        details: dict[str, Any] | None = None,
        message_id: uuid.UUID | None = None,
    ) -> Operation:
        validated_progress = validate_progress_percent(progress_percent)
        safe_details = validate_event_details(details)
        operation = await self._repository.lock_operation(operation_id)
        if operation is None:
            msg = "operation not found"
            raise OperationNotFoundError(msg)
        if operation.version != expected_version:
            msg = "concurrent update detected"
            raise ConcurrentUpdateError(msg)
        if operation.state not in PROGRESS_ALLOWED_STATES:
            msg = "progress update is not allowed in the current state"
            raise InvalidProgressStateError(msg)
        return await self._repository.apply_progress_update(
            operation=operation,
            expected_version=expected_version,
            progress_percent=validated_progress,
            event_id=new_uuid7(),
            event_type=EVENT_TYPE_PROGRESS,
            details=safe_details,
            message_id=message_id,
        )
