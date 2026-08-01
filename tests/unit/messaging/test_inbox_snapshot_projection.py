"""Unit tests for snapshot create projection in the event inbox consumer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import OPERATION_COMPLETED
from cps.domain.messaging.inbox import InboxInsertResult, InboxInsertStatus
from cps.infrastructure.db.repositories.inventory import (
    InventoryPersistenceError,
    InventoryRepository,
)
from cps.infrastructure.messaging.inbox_consumer import (
    DeliveryProcessingRecord,
    EventInboxConsumer,
)
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher

pytestmark = pytest.mark.asyncio


class _RecordingInventory:
    def __init__(self) -> None:
        self.snapshot_calls: list[dict[str, Any]] = []
        self.deleted: list[tuple[str, uuid.UUID, str]] = []

    async def persist_snapshot_result(self, **kwargs: Any) -> None:
        self.snapshot_calls.append(kwargs)

    async def persist_instance_result(self, **kwargs: Any) -> None:
        return None

    async def apply_volume_attachment_result(self, **kwargs: Any) -> None:
        return None

    async def mark_resource_deleted(
        self, resource_type: str, provider_connection_id: uuid.UUID, provider_resource_id: str
    ) -> bool:
        self.deleted.append((resource_type, provider_connection_id, provider_resource_id))
        return True


class _FakeInbox:
    async def try_insert_received(self, _draft: object) -> InboxInsertResult:
        return InboxInsertResult(
            status=InboxInsertStatus.INSERTED,
            inbox_id=uuid.uuid4(),
        )

    async def mark_processed(self, _inbox_id: uuid.UUID, *, now: datetime) -> bool:
        return True


class _FakeUow:
    def __init__(self, inventory: _RecordingInventory) -> None:
        self.inventory = inventory
        self.inbox = _FakeInbox()
        self.operations = object()
        self.bindings = None
        self.committed = False

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


def _snapshot_completed_envelope(
    *,
    connection_id: uuid.UUID,
    resource: dict[str, Any] | None,
    provider_resource_id: str | None = "snap-1",
) -> MessageEnvelope:
    result: dict[str, Any] = {
        "resource_type": "snapshot",
        "operation": "create",
        "state": "SUCCEEDED",
    }
    if provider_resource_id is not None:
        result["provider_resource_id"] = provider_resource_id
    if resource is not None:
        result["resource"] = resource
    return MessageEnvelope.model_validate(
        {
            "message_id": uuid.uuid4(),
            "message_type": OPERATION_COMPLETED,
            "schema_version": "1.0",
            "occurred_at": datetime.now(UTC),
            "correlation_id": uuid.uuid4(),
            "operation_id": uuid.uuid4(),
            "provider_id": uuid.uuid4(),
            "provider_connection_id": connection_id,
            "payload": {"result": result},
        }
    )


async def test_process_inbox_projects_snapshot_create_from_resource(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    inventory = _RecordingInventory()
    uow = _FakeUow(inventory)
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=AsyncMock(),
        session_factory=object(),
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.SqlAlchemyUnitOfWork",
        lambda _factory: uow,
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.OperationInboxHandler.handle",
        AsyncMock(),
    )
    envelope = _snapshot_completed_envelope(
        connection_id=connection_id,
        resource={
            "provider_resource_id": "snap-1",
            "name": "before-upgrade",
            "provider_status": "available",
            "project_provider_resource_id": "project-1",
            "volume_provider_resource_id": "volume-1",
            "snapshot_size_gib": 20,
            "metadata": {"purpose": "release"},
            "attributes": {"description": "checkpoint"},
        },
    )

    outcome = await consumer._process_inbox(envelope, DeliveryProcessingRecord())

    assert outcome.committed is True
    assert uow.committed is True
    assert len(inventory.snapshot_calls) == 1
    call = inventory.snapshot_calls[0]
    assert call["provider_connection_id"] == connection_id
    assert call["sync_id"] is None
    assert call["snapshot"]["provider_resource_id"] == "snap-1"
    assert call["snapshot"]["name"] == "before-upgrade"


async def test_process_inbox_skips_snapshot_create_without_identity(monkeypatch) -> None:
    inventory = _RecordingInventory()
    uow = _FakeUow(inventory)
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=AsyncMock(),
        session_factory=object(),
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.SqlAlchemyUnitOfWork",
        lambda _factory: uow,
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.OperationInboxHandler.handle",
        AsyncMock(),
    )
    envelope = _snapshot_completed_envelope(
        connection_id=uuid.uuid4(),
        resource=None,
        provider_resource_id=None,
    )

    await consumer._process_inbox(envelope, DeliveryProcessingRecord())

    assert inventory.snapshot_calls == []


async def test_process_inbox_rejects_volume_attachment_non_object_resource_before_merge(
    monkeypatch,
) -> None:
    connection_id = uuid.uuid4()
    instance_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="inst-1")
    volume_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="vol-1")
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[instance_row, volume_row])
    inventory = InventoryRepository(session)

    class _UowWithInventory:
        def __init__(self) -> None:
            self.inventory = inventory
            self.inbox = _FakeInbox()
            self.operations = object()
            self.bindings = None
            self.committed = False

        async def __aenter__(self) -> _UowWithInventory:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def commit(self) -> None:
            self.committed = True

    uow = _UowWithInventory()
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=AsyncMock(),
        session_factory=object(),
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.SqlAlchemyUnitOfWork",
        lambda _factory: uow,
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.OperationInboxHandler.handle",
        AsyncMock(),
    )
    envelope = MessageEnvelope.model_validate(
        {
            "message_id": uuid.uuid4(),
            "message_type": OPERATION_COMPLETED,
            "schema_version": "1.0",
            "occurred_at": datetime.now(UTC),
            "correlation_id": uuid.uuid4(),
            "operation_id": uuid.uuid4(),
            "provider_id": uuid.uuid4(),
            "provider_connection_id": connection_id,
            "payload": {
                "result": {
                    "resource_type": "volume-attachment",
                    "operation": "attach",
                    "state": "SUCCEEDED",
                    "parameters": {
                        "server_id": "inst-1",
                        "volume_id": "vol-1",
                    },
                    "resource": "invalid-string",
                }
            },
        }
    )

    with pytest.raises(InventoryPersistenceError, match="canonical validation"):
        await consumer._process_inbox(envelope, DeliveryProcessingRecord())

    assert uow.committed is False
    session.merge.assert_not_awaited()


async def test_process_inbox_does_not_project_snapshot_update(monkeypatch) -> None:
    inventory = _RecordingInventory()
    uow = _FakeUow(inventory)
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=AsyncMock(),
        session_factory=object(),
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.SqlAlchemyUnitOfWork",
        lambda _factory: uow,
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.OperationInboxHandler.handle",
        AsyncMock(),
    )
    envelope = MessageEnvelope.model_validate(
        {
            "message_id": uuid.uuid4(),
            "message_type": OPERATION_COMPLETED,
            "schema_version": "1.0",
            "occurred_at": datetime.now(UTC),
            "correlation_id": uuid.uuid4(),
            "operation_id": uuid.uuid4(),
            "provider_id": uuid.uuid4(),
            "provider_connection_id": uuid.uuid4(),
            "payload": {
                "result": {
                    "resource_type": "snapshot",
                    "operation": "update",
                    "provider_resource_id": "snap-1",
                    "resource": {
                        "provider_resource_id": "snap-1",
                        "name": "renamed",
                    },
                }
            },
        }
    )

    await consumer._process_inbox(envelope, DeliveryProcessingRecord())

    assert inventory.snapshot_calls == []
