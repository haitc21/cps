"""Apply OPS inventory batches inside the CPS inbox transaction."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ValidationError

from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.inventory import InventoryBatchPayload
from cps.contracts.messages.types import INVENTORY_BATCH, INVENTORY_COMPLETED
from cps.domain.operations.service import EVENT_TYPE_STATE_CHANGED, OperationService
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.repositories.inventory import InventoryRepository
from cps.infrastructure.db.repositories.operations import OperationRepository


class InventoryEventError(ValueError):
    """Non-retryable inventory event contract/ownership failure."""


class InventoryCompletedPayload(BaseModel):
    sync_id: uuid.UUID
    collections: list[str]
    status: str


class InventoryInboxHandler:
    """Validate inventory event ownership and persist the event atomically."""

    def __init__(self, repository: InventoryRepository, operations: OperationRepository) -> None:
        self._repository = repository
        self._operations = operations

    async def handle(self, envelope: MessageEnvelope) -> None:
        if envelope.message_type == INVENTORY_BATCH:
            await self._handle_batch(envelope)
            return
        if envelope.message_type == INVENTORY_COMPLETED:
            await self._handle_completed(envelope)
            return
        raise InventoryEventError("unsupported inventory event type")

    async def _handle_batch(self, envelope: MessageEnvelope) -> None:
        try:
            batch = InventoryBatchPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            raise InventoryEventError("inventory batch payload is invalid") from exc
        sync = await self._repository.get_sync(batch.sync_id)
        if sync is None or sync.operation_id != envelope.operation_id:
            raise InventoryEventError("inventory batch does not belong to operation")
        if sync.provider_connection_id != envelope.provider_connection_id:
            raise InventoryEventError("inventory batch connection ownership mismatch")
        await self._repository.persist_batch(
            sync=sync,
            message_id=envelope.message_id,
            provider_connection_id=envelope.provider_connection_id,
            batch=batch,
        )

    async def _handle_completed(self, envelope: MessageEnvelope) -> None:
        try:
            completed = InventoryCompletedPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            raise InventoryEventError("inventory completion payload is invalid") from exc
        if completed.status != "SUCCEEDED":
            raise InventoryEventError("inventory completion status is invalid")
        sync = await self._repository.get_sync(completed.sync_id)
        if sync is None or sync.operation_id != envelope.operation_id:
            raise InventoryEventError("inventory completion does not belong to operation")
        if sync.provider_connection_id != envelope.provider_connection_id:
            raise InventoryEventError("inventory completion connection ownership mismatch")
        await self._repository.finalize_sync(sync.id)
        operation = await self._operations.lock_operation(envelope.operation_id)
        if operation is None:
            raise InventoryEventError("inventory operation not found")
        if operation.state not in {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }:
            if operation.state is OperationState.QUEUED:
                operation = await OperationService(self._operations).transition_operation(
                    operation_id=operation.id,
                    expected_version=operation.version,
                    to_state=OperationState.RUNNING,
                    details={"status": "RUNNING"},
                    message_id=envelope.message_id,
                )
            await self._operations.apply_terminal_completion(
                operation=operation,
                expected_version=operation.version,
                result_payload={
                    "status": "SUCCEEDED",
                    "sync_id": str(sync.id),
                    "collections": completed.collections,
                },
                event_id=new_uuid7(),
                event_type=EVENT_TYPE_STATE_CHANGED,
                message_id=envelope.message_id,
                from_state=operation.state,
                to_state=OperationState.SUCCEEDED,
            )
