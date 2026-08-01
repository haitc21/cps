from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import OPERATION_COMPLETED
from cps.domain.operations.errors import InvalidOperationTransitionError
from cps.domain.operations.inbox_handler import OperationInboxHandler
from cps.infrastructure.messaging.inbox_consumer import DeliveryProcessingRecord, EventInboxConsumer
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher
from tests.unit.messaging.test_inbox_snapshot_projection import (
    _FakeUow,
    _RecordingInventory,
)

pytestmark = pytest.mark.asyncio


class _FlavorInventory(_RecordingInventory):
    def __init__(self) -> None:
        super().__init__()
        self.flavor_calls = []

    async def persist_flavor_result(self, **kwargs):
        self.flavor_calls.append(kwargs)


def _envelope(resource: dict[str, object]) -> MessageEnvelope:
    return MessageEnvelope.model_validate(
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
                    "schema_version": "1.0",
                    "operation_id": str(uuid.uuid4()),
                    "resource_type": "flavor",
                    "operation": "create",
                    "state": "SUCCEEDED",
                    "provider_resource_id": "flavor-1",
                    "resource": resource,
                    "error": None,
                }
            },
        }
    )


def _resource() -> dict[str, object]:
    return {
        "provider_resource_id": "flavor-1",
        "name": "small",
        "vcpus": 1,
        "ram_mib": 512,
        "root_disk_gib": 0,
        "ephemeral_disk_gib": 0,
        "swap_mib": 0,
        "is_public": True,
        "access_project_ids": [],
        "extra_specs": {},
    }


async def _consumer(monkeypatch, inventory):
    uow = _FakeUow(inventory)
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.SqlAlchemyUnitOfWork", lambda _: uow
    )
    monkeypatch.setattr(
        "cps.infrastructure.messaging.inbox_consumer.OperationInboxHandler.handle",
        AsyncMock(return_value=True),
    )
    return (
        EventInboxConsumer(
            lifecycle=WorkerLifecycle(),
            publisher=ConfirmedPublisher(),
            retry_exchange=AsyncMock(),
            session_factory=object(),
        ),
        uow,
    )


async def test_validated_flavor_result_projects_before_commit(monkeypatch):
    inventory = _FlavorInventory()
    consumer, uow = await _consumer(monkeypatch, inventory)
    await consumer._process_inbox(_envelope(_resource()), DeliveryProcessingRecord())
    assert len(inventory.flavor_calls) == 1
    assert uow.committed is True


async def test_invalid_flavor_result_rolls_back_without_projection(monkeypatch):
    inventory = _FlavorInventory()
    consumer, uow = await _consumer(monkeypatch, inventory)
    resource = _resource()
    del resource["ram_mib"]
    with pytest.raises(ValidationError):
        await consumer._process_inbox(_envelope(resource), DeliveryProcessingRecord())
    assert inventory.flavor_calls == []
    assert uow.committed is False


async def test_flavor_result_must_bind_operation_and_provider_identity():
    result = _envelope(_resource()).payload["result"]
    operation_id = uuid.UUID(result["operation_id"])
    operation = type(
        "OperationStub",
        (),
        {
            "id": operation_id,
            "operation_type": "openstack.flavor.delete",
            "request_payload": {"provider_resource_id": "flavor-other"},
        },
    )()
    with pytest.raises(InvalidOperationTransitionError):
        OperationInboxHandler._validate_flavor_completion(operation, result)
