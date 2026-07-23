"""Apply OPS operation events inside inbox transactions."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from cps.contracts.errors import CommonError
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import (
    CONNECTION_VALIDATE,
    OPERATION_COMPLETED,
    OPERATION_FAILED,
    OPERATION_PROGRESS,
)
from cps.contracts.validation import CapabilityDocument, ValidationProgress
from cps.domain.operations.errors import (
    EventOwnershipMismatchError,
    InvalidOperationTransitionError,
    InvalidProgressStateError,
    OperationNotFoundError,
)
from cps.domain.operations.event_details import validate_event_details
from cps.domain.operations.progress import validate_progress_percent
from cps.domain.operations.service import (
    EVENT_TYPE_LATE_RESULT,
    EVENT_TYPE_STATE_CHANGED,
    OperationService,
)
from cps.domain.operations.states import TERMINAL_STATES
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.repositories.operations import OperationRepository

SUPPORTED_EVENT_TYPES = frozenset(
    {
        OPERATION_PROGRESS,
        OPERATION_COMPLETED,
        OPERATION_FAILED,
    }
)


class UnsupportedEventTypeError(ValueError):
    """Raised when an event type is not handled by the inbox consumer."""


class OperationInboxHandler:
    """Domain handler for cloud operation events from OPS."""

    def __init__(self, repository: OperationRepository) -> None:
        self._repository = repository
        self._service = OperationService(repository)

    async def handle(self, envelope: MessageEnvelope) -> None:
        if envelope.message_type not in SUPPORTED_EVENT_TYPES:
            msg = "unsupported event type"
            raise UnsupportedEventTypeError(msg)

        operation = await self._repository.lock_operation(envelope.operation_id)
        if operation is None:
            msg = "operation not found"
            raise OperationNotFoundError(msg)

        await self._assert_event_ownership(envelope, operation)

        message_id = envelope.message_id
        if envelope.message_type == OPERATION_PROGRESS:
            await self._handle_progress(envelope, operation, message_id=message_id)
            return
        if envelope.message_type == OPERATION_COMPLETED:
            await self._handle_completed(envelope, operation, message_id=message_id)
            return
        await self._handle_failed(envelope, operation, message_id=message_id)

    async def _assert_event_ownership(
        self,
        envelope: MessageEnvelope,
        operation: Operation,
    ) -> None:
        if operation.provider_connection_id != envelope.provider_connection_id:
            msg = "event provider connection does not match operation"
            raise EventOwnershipMismatchError(msg)
        connection = await self._repository.get_provider_connection(
            operation.provider_connection_id
        )
        if connection is None or connection.provider_id != envelope.provider_id:
            msg = "event provider does not match operation connection"
            raise EventOwnershipMismatchError(msg)

    async def _handle_progress(
        self,
        envelope: MessageEnvelope,
        operation: Operation,
        *,
        message_id: uuid.UUID,
    ) -> None:
        if operation.state in TERMINAL_STATES:
            msg = "progress update is not allowed in the current state"
            raise InvalidProgressStateError(msg)
        progress_model = ValidationProgress.model_validate(envelope.payload)
        progress_raw = progress_model.progress
        if not isinstance(progress_raw, int):
            msg = "progress value is invalid"
            raise InvalidProgressStateError(msg)
        progress = validate_progress_percent(progress_raw)
        if progress_model.state == "RUNNING" and operation.state == OperationState.QUEUED:
            operation = await self._service.transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.RUNNING,
                details={"status": "RUNNING"},
                message_id=message_id,
            )
        elif (
            progress_model.state == "WAITING_PROVIDER" and operation.state == OperationState.RUNNING
        ):
            operation = await self._service.transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.WAITING_PROVIDER,
                details={"status": "WAITING_PROVIDER"},
                message_id=message_id,
            )
        elif progress_model.state == "RUNNING" and operation.state != OperationState.RUNNING:
            raise InvalidProgressStateError("progress state is invalid")
        details = validate_event_details(
            {
                "progress": progress,
                "message": envelope.payload.get("message"),
            }
        )
        await self._service.record_progress(
            operation_id=operation.id,
            expected_version=operation.version,
            progress_percent=progress,
            details=details.to_dict(),
            message_id=message_id,
        )

    async def _handle_completed(
        self,
        envelope: MessageEnvelope,
        operation: Operation,
        *,
        message_id: uuid.UUID,
    ) -> None:
        result_payload = envelope.payload.get("result")
        if not isinstance(result_payload, dict):
            msg = "completed result payload is invalid"
            raise InvalidOperationTransitionError(msg)
        safe_result = validate_event_details({"result": result_payload}).to_dict()["result"]
        if operation.state in TERMINAL_STATES:
            await self._append_late_result(
                operation=operation,
                message_id=message_id,
                details={"event_type": OPERATION_COMPLETED, "result": safe_result},
            )
            return
        to_state = OperationState.SUCCEEDED
        validate_transition_target(operation.state, to_state)
        if operation.operation_type == CONNECTION_VALIDATE:
            capabilities = CapabilityDocument.model_validate(result_payload.get("capabilities", {}))
            await self._repository.apply_connection_validation(
                operation.provider_connection_id,
                capabilities=capabilities.model_dump(mode="json"),
                valid=True,
            )
        await self._repository.apply_terminal_completion(
            operation=operation,
            expected_version=operation.version,
            result_payload=safe_result,
            event_id=new_uuid7(),
            event_type=EVENT_TYPE_STATE_CHANGED,
            message_id=message_id,
            from_state=operation.state,
            to_state=to_state,
        )

    async def _handle_failed(
        self,
        envelope: MessageEnvelope,
        operation: Operation,
        *,
        message_id: uuid.UUID,
    ) -> None:
        error_raw = envelope.payload.get("error")
        if not isinstance(error_raw, dict):
            msg = "failed error payload is invalid"
            raise InvalidOperationTransitionError(msg)
        try:
            common_error = CommonError.model_validate(error_raw)
        except ValidationError as exc:
            msg = "failed error payload is invalid"
            raise InvalidOperationTransitionError(msg) from exc
        error_payload = common_error.model_dump(mode="json")
        if operation.state in TERMINAL_STATES:
            await self._append_late_result(
                operation=operation,
                message_id=message_id,
                details={"event_type": OPERATION_FAILED, "error_code": common_error.code},
            )
            return
        to_state = OperationState.FAILED
        validate_transition_target(operation.state, to_state)
        await self._repository.apply_connection_validation(
            operation.provider_connection_id,
            validation_error=error_payload,
            valid=False,
            pending=common_error.retryable,
        )
        await self._repository.apply_terminal_failure(
            operation=operation,
            expected_version=operation.version,
            error_payload=error_payload,
            event_id=new_uuid7(),
            event_type=EVENT_TYPE_STATE_CHANGED,
            message_id=message_id,
            from_state=operation.state,
            to_state=to_state,
            provider_request_id=common_error.provider_request_id,
        )

    async def _append_late_result(
        self,
        *,
        operation: Operation,
        message_id: uuid.UUID,
        details: dict[str, Any],
    ) -> None:
        safe_details = validate_event_details(details)
        await self._repository.apply_late_result(
            operation=operation,
            event_id=new_uuid7(),
            event_type=EVENT_TYPE_LATE_RESULT,
            message_id=message_id,
            details=safe_details,
        )


def validate_transition_target(from_state: OperationState, to_state: OperationState) -> None:
    from cps.domain.operations.transitions import validate_transition

    validate_transition(from_state, to_state)
