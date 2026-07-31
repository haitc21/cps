"""Sprint 18 recovery matrix: duplicate idempotency for user-resource operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import IdempotencyKeyReusedError
from cps.contracts.messages.network_operations import (
    NetworkOperation,
    NetworkOperationRequest,
    NetworkResourceType,
)
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_operations import VolumeOperationRequest
from cps.domain.operations.service import OperationService
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState


class _Repository:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection
        self.operations: dict[tuple[uuid.UUID, str, str], SimpleNamespace] = {}

    async def get_provider_connection(self, connection_id: uuid.UUID):
        return self.connection if connection_id == self.connection.id else None

    async def get_by_idempotency_scope(
        self, *, provider_connection_id, operation_type, idempotency_key
    ):
        return self.operations.get((provider_connection_id, operation_type, idempotency_key))

    async def insert_operation(self, **kwargs):
        operation = SimpleNamespace(
            **kwargs,
            id=kwargs["operation_id"],
            state=OperationState.ACCEPTED,
            version=1,
            progress_percent=None,
            result_payload=None,
            error_payload=None,
            provider_request_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.operations[
            (kwargs["provider_connection_id"], kwargs["operation_type"], kwargs["idempotency_key"])
        ] = operation
        return operation


class _Outbox:
    def __init__(self) -> None:
        self.drafts = []

    async def add(self, draft) -> None:
        self.drafts.append(draft)


class _Inventory:
    async def resource_belongs_to_connection(self, *_args) -> bool:
        return True

    async def list_resources(self, *_args, **_kwargs):
        return [], 0


async def _queue_operation(repository: _Repository, operation_id: uuid.UUID):
    operation = next(item for item in repository.operations.values() if item.id == operation_id)
    operation.state = OperationState.QUEUED
    operation.version += 1
    return operation


@pytest.mark.asyncio
async def test_network_floating_ip_associate_idempotency_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    outbox = _Outbox()
    service = OperationApplicationService(repository, outbox, _Inventory())

    async def transition(_service, **kwargs):
        return await _queue_operation(repository, kwargs["operation_id"])

    monkeypatch.setattr(OperationService, "transition_operation", transition)

    operation_id = new_uuid7()

    def request(port_id: str) -> NetworkOperationRequest:
        return NetworkOperationRequest(
            operation_id=operation_id,
            resource_type=NetworkResourceType.FLOATING_IP,
            operation=NetworkOperation.ASSOCIATE,
            required_scope=ScopeKind.PROJECT,
            provider_connection_id=connection_id,
            provider_resource_id="fip-1",
            port_provider_resource_id=port_id,
        )

    first = await service.create_network_operation(
        connection_id,
        idempotency_key="fip-associate-key",
        correlation_id=uuid.uuid4(),
        request=request("port-1"),
    )
    replay = await service.create_network_operation(
        connection_id,
        idempotency_key="fip-associate-key",
        correlation_id=uuid.uuid4(),
        request=request("port-1"),
    )

    assert first.id == replay.id == operation_id
    assert outbox.drafts[0].message_id.version == 7
    assert outbox.drafts[0].message_type == "openstack.floating.ip.associate"
    assert outbox.drafts[0].payload["payload"]["parameters"]["port_id"] == "port-1"
    assert len(outbox.drafts) == 1

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_network_operation(
            connection_id,
            idempotency_key="fip-associate-key",
            correlation_id=uuid.uuid4(),
            request=request("port-2"),
        )


@pytest.mark.asyncio
async def test_volume_and_network_idempotency_use_distinct_operation_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    outbox = _Outbox()
    service = OperationApplicationService(repository, outbox, _Inventory())

    async def transition(_service, **kwargs):
        return await _queue_operation(repository, kwargs["operation_id"])

    monkeypatch.setattr(OperationService, "transition_operation", transition)

    volume = await service.create_volume_operation(
        connection_id,
        idempotency_key="shared-key",
        correlation_id=uuid.uuid4(),
        request=VolumeOperationRequest(
            operation_id=uuid.uuid4(),
            operation="create",
            required_scope=ScopeKind.PROJECT,
            provider_connection_id=connection_id,
            project_provider_resource_id="project-1",
            name="data",
            size_gib=10,
        ),
    )
    network = await service.create_network_operation(
        connection_id,
        idempotency_key="shared-key",
        correlation_id=uuid.uuid4(),
        request=NetworkOperationRequest(
            operation_id=new_uuid7(),
            resource_type=NetworkResourceType.FLOATING_IP,
            operation=NetworkOperation.ASSOCIATE,
            required_scope=ScopeKind.PROJECT,
            provider_connection_id=connection_id,
            provider_resource_id="fip-1",
            port_provider_resource_id="port-1",
        ),
    )

    assert volume.id != network.id
    assert len(outbox.drafts) == 2
    assert {draft.message_type for draft in outbox.drafts} == {
        "openstack.volume.create",
        "openstack.floating.ip.associate",
    }
