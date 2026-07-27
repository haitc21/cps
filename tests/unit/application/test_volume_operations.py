"""Focused tests for volume operation idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import IdempotencyKeyReusedError
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_operations import VolumeOperationRequest
from cps.domain.operations.service import OperationService
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


@pytest.mark.asyncio
async def test_volume_operation_idempotency_is_deterministic(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    outbox = _Outbox()
    service = OperationApplicationService(repository, outbox)

    async def transition(_service, **kwargs):
        return await _queued(repository, kwargs["operation_id"])

    monkeypatch.setattr(OperationService, "transition_operation", transition)

    def request(size_gib: int, operation_id: uuid.UUID) -> VolumeOperationRequest:
        return VolumeOperationRequest(
            operation_id=operation_id,
            operation="create",
            required_scope=ScopeKind.PROJECT,
            provider_connection_id=connection_id,
            project_provider_resource_id="project-1",
            name="data",
            size_gib=size_gib,
        )

    first = await service.create_volume_operation(
        connection_id,
        idempotency_key="volume-key-1",
        correlation_id=uuid.uuid4(),
        request=request(10, uuid.uuid4()),
    )
    replay = await service.create_volume_operation(
        connection_id,
        idempotency_key="volume-key-1",
        correlation_id=uuid.uuid4(),
        request=request(10, uuid.uuid4()),
    )

    expected_operation_id = uuid.uuid5(connection_id, "volume-operation:volume-key-1")
    expected_message_id = uuid.uuid5(expected_operation_id, "volume-command")
    assert first.id == replay.id == expected_operation_id
    assert outbox.drafts[0].message_id == expected_message_id
    assert len(outbox.drafts) == 1

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_volume_operation(
            connection_id,
            idempotency_key="volume-key-1",
            correlation_id=uuid.uuid4(),
            request=request(20, uuid.uuid4()),
        )


async def _queued(repository: _Repository, operation_id: uuid.UUID):
    operation = repository.operations[
        next(
            key
            for key in repository.operations
            if key[0] == repository.connection.id and key[1] == "openstack.volume.create" and key[2]
        )
    ]
    operation.state = OperationState.QUEUED
    operation.version += 1
    return operation
