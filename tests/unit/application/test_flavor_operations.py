"""Focused durable flavor-operation coverage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import IdempotencyKeyReusedError
from cps.contracts.messages.flavor_operations import FlavorOperationRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import OperationState


class _Repository:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection
        self.operations: dict[tuple[uuid.UUID, str, str], SimpleNamespace] = {}

    async def get_provider_connection(self, connection_id: uuid.UUID):
        return self.connection if connection_id == self.connection.id else None

    async def get_by_idempotency_scope(self, **kwargs):
        return self.operations.get(
            (kwargs["provider_connection_id"], kwargs["operation_type"], kwargs["idempotency_key"])
        )

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
async def test_flavor_create_is_durable_and_idempotent(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(
        id=connection_id,
        provider_id=uuid.uuid4(),
        capabilities={"features": {"flavor.create": {"supported": True}}},
    )
    repository = _Repository(connection)
    outbox = _Outbox()
    service = OperationApplicationService(repository, outbox)

    async def transition(_service, **kwargs):
        operation = repository.operations[
            (connection_id, "openstack.flavor.create", "flavor-key-1")
        ]
        operation.state = OperationState.QUEUED
        operation.version += 1
        return operation

    monkeypatch.setattr(OperationService, "transition_operation", transition)

    def request(ram_mib: int) -> FlavorOperationRequest:
        return FlavorOperationRequest(
            operation_id=uuid.uuid4(),
            operation="create",
            provider_connection_id=connection_id,
            required_scope=ScopeKind.SYSTEM,
            name="cmp-s19-small",
            vcpus=1,
            ram_mib=ram_mib,
            disk_gib=10,
            is_public=False,
        )

    first = await service.create_flavor_operation(
        connection_id,
        idempotency_key="flavor-key-1",
        correlation_id=uuid.uuid4(),
        request=request(1024),
    )
    replay = await service.create_flavor_operation(
        connection_id,
        idempotency_key="flavor-key-1",
        correlation_id=uuid.uuid4(),
        request=request(1024),
    )

    assert first.id == replay.id == uuid.uuid5(connection_id, "flavor:flavor-key-1")
    assert len(outbox.drafts) == 1
    assert outbox.drafts[0].message_type == "openstack.flavor.create"
    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_flavor_operation(
            connection_id,
            idempotency_key="flavor-key-1",
            correlation_id=uuid.uuid4(),
            request=request(2048),
        )


def test_flavor_contract_rejects_immutable_shape_update_and_public_access() -> None:
    with pytest.raises(ValueError, match="greater than or equal"):
        FlavorOperationRequest(
            operation_id=uuid.uuid4(),
            operation="create",
            provider_connection_id=uuid.uuid4(),
            name="bad",
            vcpus=0,
            ram_mib=1024,
            disk_gib=10,
        )
    with pytest.raises(ValueError, match="private flavor"):
        FlavorOperationRequest(
            operation_id=uuid.uuid4(),
            operation="replace_access",
            provider_connection_id=uuid.uuid4(),
            provider_resource_id="flavor-1",
            is_public=True,
            access_project_ids=["project-1"],
        )
