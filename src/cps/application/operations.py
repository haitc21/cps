"""Operation projections and validation-command creation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cps.api.schemas.operations import (
    OperationEventPage,
    OperationEventView,
    OperationPage,
    OperationPageInfo,
    OperationView,
)
from cps.contracts.errors import (
    IdempotencyKeyReusedError,
    OperationNotFoundPublicError,
    ProviderConnectionNotFoundError,
)
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import CONNECTION_VALIDATE
from cps.domain.messaging.outbox import OutboxDraft
from cps.domain.operations.create import create_operation_idempotent
from cps.domain.operations.errors import IdempotencyConflictError
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.repositories.operations import OperationRepository
from cps.infrastructure.db.repositories.outbox import OutboxRepository


def to_view(operation: object) -> OperationView:
    return OperationView.model_validate(operation, from_attributes=True)


class OperationApplicationService:
    def __init__(self, repository: OperationRepository, outbox: OutboxRepository) -> None:
        self._repository = repository
        self._outbox = outbox

    async def create_validation(
        self, connection_id: uuid.UUID, *, idempotency_key: str, correlation_id: uuid.UUID
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        operation_id = _uuid7()
        message_id = _uuid7()
        occurred_at = datetime.now(UTC)
        request_payload = {"validation_mode": "SAFE_READ_ONLY"}
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": CONNECTION_VALIDATE,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "causation_id": None,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "credential_reference": connection.credential_id,
                "trace_context": {},
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=CONNECTION_VALIDATE,
            routing_key=CONNECTION_VALIDATE,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=CONNECTION_VALIDATE,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def get(self, operation_id: uuid.UUID) -> OperationView:
        operation = await self._repository.get_operation(operation_id)
        if operation is None:
            raise OperationNotFoundPublicError
        return to_view(operation)

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        connection_id: uuid.UUID | None = None,
        operation_type: str | None = None,
        state: OperationState | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> OperationPage:
        rows, total = await self._repository.list_operations(
            offset=offset,
            limit=limit,
            provider_connection_id=connection_id,
            operation_type=operation_type,
            state=state,
            created_from=created_from,
            created_to=created_to,
        )
        return OperationPage(
            items=[to_view(row) for row in rows],
            page=OperationPageInfo(offset=offset, limit=limit, total=total),
        )

    async def events(
        self, operation_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> OperationEventPage:
        if await self._repository.get_operation(operation_id) is None:
            raise OperationNotFoundPublicError
        rows = await self._repository.get_events(operation_id)
        items = [
            OperationEventView.model_validate(
                {
                    "id": event.id,
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "from_state": event.from_state,
                    "to_state": event.to_state,
                    "message_id": event.message_id,
                    "details": event.details,
                    "occurred_at": event.occurred_at,
                }
            )
            for event in rows[offset : offset + limit]
        ]
        return OperationEventPage(
            items=items,
            page=OperationPageInfo(offset=offset, limit=limit, total=len(rows)),
        )


def _uuid7() -> uuid.UUID:
    from cps.identifiers import new_uuid7

    return new_uuid7()
