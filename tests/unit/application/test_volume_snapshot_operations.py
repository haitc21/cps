"""VL-01: volume snapshot update/delete ownership when inventory projection lags."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import ProviderConnectionNotFoundError
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_snapshot_operations import (
    VolumeSnapshotOperation,
    VolumeSnapshotOperationRequest,
)
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import OperationState


class _Repository:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection
        self.operations: dict[tuple[uuid.UUID, str, str], SimpleNamespace] = {}
        self.cps_snapshots: set[tuple[uuid.UUID, str]] = set()
        self.cps_snapshot_projects: dict[tuple[uuid.UUID, str], str | None] = {}

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

    async def cps_created_volume_snapshot_exists(
        self,
        *,
        provider_connection_id: uuid.UUID,
        provider_resource_id: str,
        project_provider_resource_id: str | None = None,
    ) -> bool:
        key = (provider_connection_id, provider_resource_id)
        if key not in self.cps_snapshots:
            return False
        stored_project = self.cps_snapshot_projects.get(key)
        if project_provider_resource_id is None or stored_project is None:
            return True
        return stored_project == project_provider_resource_id


class _Inventory:
    def __init__(self) -> None:
        self.snapshots: dict[tuple[uuid.UUID, str], SimpleNamespace] = {}

    async def resource_belongs_to_connection(
        self, resource_type: str, provider_connection_id: uuid.UUID, provider_resource_id: str
    ) -> bool:
        assert resource_type in {"volume-snapshot", "snapshot"}
        row = self.snapshots.get((provider_connection_id, provider_resource_id))
        return row is not None and row.lifecycle_state != "DELETED"

    async def list_resources(
        self,
        resource_type: str,
        *,
        offset: int,
        limit: int,
        provider_connection_id: uuid.UUID | None = None,
        provider_resource_id: str | None = None,
        **_: object,
    ) -> tuple[list[SimpleNamespace], int]:
        assert resource_type in {"volume-snapshot", "snapshot"}
        if provider_connection_id is None or provider_resource_id is None:
            return [], 0
        row = self.snapshots.get((provider_connection_id, provider_resource_id))
        return ([row], 1) if row is not None else ([], 0)


class _Outbox:
    def __init__(self) -> None:
        self.drafts = []

    async def add(self, draft) -> None:
        self.drafts.append(draft)


def _service(
    repository: _Repository, inventory: _Inventory | None = None
) -> OperationApplicationService:
    return OperationApplicationService(repository, _Outbox(), inventory=inventory)


def _request(
    operation: str,
    *,
    connection_id: uuid.UUID,
    provider_resource_id: str | None = None,
    project_provider_resource_id: str | None = None,
    name: str | None = None,
) -> VolumeSnapshotOperationRequest:
    return VolumeSnapshotOperationRequest(
        operation_id=uuid.uuid4(),
        provider_connection_id=connection_id,
        operation=operation,
        required_scope=ScopeKind.PROJECT,
        provider_resource_id=provider_resource_id,
        project_provider_resource_id=project_provider_resource_id,
        volume_provider_resource_id="volume-1" if operation == "create" else None,
        name=name or ("snap" if operation == "create" else "updated"),
    )


@pytest.mark.asyncio
async def test_snapshot_update_allowed_when_inventory_projected(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    inventory = _Inventory()
    inventory.snapshots[(connection_id, "snap-1")] = SimpleNamespace(
        lifecycle_state="ACTIVE",
        project_provider_resource_id="project-1",
    )
    service = _service(repository, inventory)
    monkeypatch.setattr(OperationService, "transition_operation", _transition)

    view = await service.create_volume_snapshot_operation(
        connection_id,
        idempotency_key="snap-update-inventory",
        correlation_id=uuid.uuid4(),
        request=_request("update", connection_id=connection_id, provider_resource_id="snap-1"),
    )

    assert view.state == OperationState.QUEUED
    assert len(repository.operations) == 1


@pytest.mark.asyncio
async def test_snapshot_update_allowed_when_cps_create_not_yet_projected(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    repository.cps_snapshots.add((connection_id, "snap-cps-1"))
    inventory = _Inventory()
    service = _service(repository, inventory)
    monkeypatch.setattr(OperationService, "transition_operation", _transition)

    view = await service.create_volume_snapshot_operation(
        connection_id,
        idempotency_key="snap-update-delayed",
        correlation_id=uuid.uuid4(),
        request=_request("update", connection_id=connection_id, provider_resource_id="snap-cps-1"),
    )

    assert view.state == OperationState.QUEUED


@pytest.mark.asyncio
async def test_snapshot_delete_allowed_when_cps_create_not_yet_projected(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    repository.cps_snapshots.add((connection_id, "snap-cps-2"))
    inventory = _Inventory()
    service = _service(repository, inventory)
    monkeypatch.setattr(OperationService, "transition_operation", _transition)

    view = await service.create_volume_snapshot_operation(
        connection_id,
        idempotency_key="snap-delete-delayed",
        correlation_id=uuid.uuid4(),
        request=_request("delete", connection_id=connection_id, provider_resource_id="snap-cps-2"),
    )

    assert view.state == OperationState.QUEUED


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_snapshot_lifecycle_rejects_missing_provider_resource_id(operation: str) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    service = _service(repository, _Inventory())
    request = VolumeSnapshotOperationRequest.model_construct(
        operation_id=uuid.uuid4(),
        provider_connection_id=connection_id,
        operation=VolumeSnapshotOperation.UPDATE
        if operation == "update"
        else VolumeSnapshotOperation.DELETE,
        required_scope=ScopeKind.PROJECT,
        provider_resource_id=None,
        name="updated" if operation == "update" else None,
    )

    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_volume_snapshot_operation(
            connection_id,
            idempotency_key=f"snap-{operation}-missing-id",
            correlation_id=uuid.uuid4(),
            request=request,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_snapshot_lifecycle_rejects_foreign_provider_resource_id(operation: str) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    service = _service(repository, _Inventory())

    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_volume_snapshot_operation(
            connection_id,
            idempotency_key=f"snap-{operation}-foreign",
            correlation_id=uuid.uuid4(),
            request=_request(
                operation, connection_id=connection_id, provider_resource_id="foreign-snap"
            ),
        )


@pytest.mark.asyncio
async def test_snapshot_update_rejects_foreign_project_when_inventory_projected() -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    inventory = _Inventory()
    inventory.snapshots[(connection_id, "snap-1")] = SimpleNamespace(
        lifecycle_state="ACTIVE",
        project_provider_resource_id="project-a",
    )
    service = _service(repository, inventory)

    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_volume_snapshot_operation(
            connection_id,
            idempotency_key="snap-update-wrong-project",
            correlation_id=uuid.uuid4(),
            request=_request(
                "update",
                connection_id=connection_id,
                provider_resource_id="snap-1",
                project_provider_resource_id="project-b",
            ),
        )


@pytest.mark.asyncio
async def test_snapshot_update_rejects_foreign_project_when_only_cps_create_exists() -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = _Repository(connection)
    repository.cps_snapshots.add((connection_id, "snap-cps-3"))
    repository.cps_snapshot_projects[(connection_id, "snap-cps-3")] = "project-a"
    service = _service(repository, _Inventory())

    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_volume_snapshot_operation(
            connection_id,
            idempotency_key="snap-update-cps-wrong-project",
            correlation_id=uuid.uuid4(),
            request=_request(
                "update",
                connection_id=connection_id,
                provider_resource_id="snap-cps-3",
                project_provider_resource_id="project-b",
            ),
        )


async def _transition(_service, **kwargs):
    repository = _service._repository
    operation_id = kwargs["operation_id"]
    operation = next(op for op in repository.operations.values() if op.id == operation_id)
    operation.state = OperationState.QUEUED
    operation.version += 1
    return operation
