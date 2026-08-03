"""CPS-1904 durable instance snapshot application tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import InstanceStateConflictError, ProviderConnectionNotFoundError
from cps.contracts.messages.instance_snapshot_operations import InstanceSnapshotRequest
from cps.contracts.messages.types import INSTANCE_SNAPSHOT_CREATE
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import OperationState


class _Repository:
    def __init__(self, connection: object) -> None:
        self.connection = connection
        self.operations: dict[tuple[uuid.UUID, str, str], object] = {}

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
        self.drafts: list[object] = []

    async def add(self, draft: object) -> None:
        self.drafts.append(draft)


class _Inventory:
    def __init__(self, instance: object) -> None:
        self.instance = instance

    async def list_resources(self, resource_type: str, **_kwargs):
        return ([self.instance], 1) if resource_type == "instance" else ([], 0)


def _request(connection_id: uuid.UUID, **overrides: object) -> InstanceSnapshotRequest:
    values: dict[str, object] = {
        "operation_id": uuid.uuid4(),
        "provider_connection_id": connection_id,
        "instance_provider_resource_id": "server-1",
        "project_provider_resource_id": "project-1",
        "name": "before-upgrade",
    }
    values.update(overrides)
    return InstanceSnapshotRequest(**values)


@pytest.mark.asyncio
async def test_snapshot_is_durable_and_replay_uses_one_outbox_message(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(
        id=connection_id,
        provider_id=uuid.uuid4(),
        scope_project_provider_resource_id="project-1",
        capabilities={"features": {"instance.snapshot": {"supported": True}}},
    )
    repository = _Repository(connection)
    outbox = _Outbox()
    service = OperationApplicationService(
        repository,
        outbox,
        _Inventory(
            SimpleNamespace(
                project_provider_resource_id="project-1",
                lifecycle_state="ACTIVE",
                provider_status="ACTIVE",
            )
        ),
    )

    async def transition(_service, **kwargs):
        operation = repository.operations[(connection_id, INSTANCE_SNAPSHOT_CREATE, "snapshot-1")]
        operation.state = OperationState.QUEUED
        operation.version += 1
        return operation

    monkeypatch.setattr(OperationService, "transition_operation", transition)
    first = await service.create_instance_snapshot(
        connection_id,
        idempotency_key="snapshot-1",
        correlation_id=uuid.uuid4(),
        request=_request(connection_id),
    )
    replay = await service.create_instance_snapshot(
        connection_id,
        idempotency_key="snapshot-1",
        correlation_id=uuid.uuid4(),
        request=_request(connection_id),
    )

    assert first.id == replay.id == uuid.uuid5(connection_id, "instance-snapshot:snapshot-1")
    assert len(outbox.drafts) == 1
    payload = outbox.drafts[0].payload["payload"]
    assert payload["instance_provider_resource_id"] == "server-1"
    assert "image_bytes" not in payload


@pytest.mark.asyncio
async def test_snapshot_rejects_foreign_or_non_active_instance() -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(
        id=connection_id,
        provider_id=uuid.uuid4(),
        scope_project_provider_resource_id="project-1",
        capabilities={"features": {"instance.snapshot": True}},
    )
    service = OperationApplicationService(
        _Repository(connection),
        _Outbox(),
        _Inventory(
            SimpleNamespace(
                project_provider_resource_id="other",
                lifecycle_state="ACTIVE",
                provider_status="ACTIVE",
            )
        ),
    )
    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_instance_snapshot(
            connection_id,
            idempotency_key="snapshot-foreign",
            correlation_id=uuid.uuid4(),
            request=_request(connection_id),
        )

    service = OperationApplicationService(
        _Repository(connection),
        _Outbox(),
        _Inventory(
            SimpleNamespace(
                project_provider_resource_id="project-1",
                lifecycle_state="ACTIVE",
                provider_status="SHUTOFF",
            )
        ),
    )
    with pytest.raises(InstanceStateConflictError):
        await service.create_instance_snapshot(
            connection_id,
            idempotency_key="snapshot-stopped",
            correlation_id=uuid.uuid4(),
            request=_request(connection_id),
        )
