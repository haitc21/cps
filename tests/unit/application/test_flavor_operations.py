from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import (
    CapabilityUnsupportedError,
    IdempotencyKeyReusedError,
    ProviderConnectionNotFoundError,
)
from cps.contracts.messages.flavor_operations import FlavorCreateRequest, FlavorDeleteRequest
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus, OperationState


class _Repository:
    def __init__(self, connection):
        self.connection = connection
        self.operations = {}

    async def get_provider_connection(self, connection_id):
        return self.connection if connection_id == self.connection.id else None

    async def get_by_idempotency_scope(self, **scope):
        return self.operations.get(tuple(scope.values()))

    async def get_by_connection_idempotency_key(self, **scope):
        return next(
            (
                row
                for (connection_id, _operation_type, key), row in self.operations.items()
                if connection_id == scope["provider_connection_id"]
                and key == scope["idempotency_key"]
            ),
            None,
        )

    async def lock_connection_idempotency_key(self, **_scope):
        return None

    async def insert_operation(self, **kwargs):
        row = SimpleNamespace(
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
        key = (
            kwargs["provider_connection_id"],
            kwargs["operation_type"],
            kwargs["idempotency_key"],
        )
        self.operations[key] = row
        return row


class _Outbox:
    def __init__(self):
        self.drafts = []

    async def add(self, draft):
        self.drafts.append(draft)


class _Inventory:
    def __init__(self, *, flavor_state=(False, False)):
        self.flavor_state = flavor_state

    async def resource_name_belongs_to_connection(self, *_):
        return False

    async def live_flavor_name_exists_case_insensitive(self, *_):
        return False

    async def resource_belongs_to_connection(self, *_):
        return False

    async def project_provider_ids_belong_to_provider(self, *_):
        return True

    async def flavor_mutation_state(self, *_):
        return self.flavor_state

    async def flavor_is_used_on_provider(self, *_):
        return False


def _connection(scope=ConnectionScopeKind.SYSTEM, supported=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        status=ConnectionStatus.VALID,
        scope_kind=scope,
        capabilities={"features": {"flavor.create": {"supported": supported}}},
    )


def _request(connection_id, ram=512):
    return FlavorCreateRequest(
        operation_id=uuid.uuid4(),
        provider_connection_id=connection_id,
        name="small",
        vcpus=1,
        ram_mib=ram,
        root_disk_gib=0,
        is_public=True,
    )


@pytest.mark.asyncio
async def test_create_is_deterministic_and_rejects_changed_replay(monkeypatch):
    connection = _connection()
    repository, outbox = _Repository(connection), _Outbox()
    service = OperationApplicationService(repository, outbox, _Inventory())

    async def transition(_service, **kwargs):
        row = next(
            row for row in repository.operations.values() if row.id == kwargs["operation_id"]
        )
        row.state, row.version = OperationState.QUEUED, row.version + 1
        return row

    monkeypatch.setattr(OperationService, "transition_operation", transition)
    first = await service.create_flavor_operation(
        connection.id,
        idempotency_key="same",
        correlation_id=uuid.uuid4(),
        request=_request(connection.id),
    )
    replay = await service.create_flavor_operation(
        connection.id,
        idempotency_key="same",
        correlation_id=uuid.uuid4(),
        request=_request(connection.id),
    )
    assert first.id == replay.id == uuid.uuid5(connection.id, "flavor:same")
    assert len(outbox.drafts) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_flavor_operation(
            connection.id,
            idempotency_key="same",
            correlation_id=uuid.uuid4(),
            request=_request(connection.id, ram=1024),
        )


@pytest.mark.asyncio
async def test_idempotency_key_cannot_cross_flavor_operation_types():
    connection = _connection()
    repository, outbox = _Repository(connection), _Outbox()
    repository.operations[(connection.id, "openstack.flavor.delete", "shared")] = SimpleNamespace(
        operation_type="openstack.flavor.delete"
    )
    service = OperationApplicationService(repository, outbox, _Inventory())
    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_flavor_operation(
            connection.id,
            idempotency_key="shared",
            correlation_id=uuid.uuid4(),
            request=_request(connection.id),
        )
    assert outbox.drafts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection", [_connection(ConnectionScopeKind.PROJECT), _connection(supported=False)]
)
async def test_create_fails_closed_without_system_scope_or_capability(connection):
    outbox = _Outbox()
    service = OperationApplicationService(_Repository(connection), outbox, _Inventory())
    with pytest.raises(CapabilityUnsupportedError):
        await service.create_flavor_operation(
            connection.id,
            idempotency_key="key",
            correlation_id=uuid.uuid4(),
            request=_request(connection.id),
        )
    assert outbox.drafts == []


@pytest.mark.asyncio
async def test_stale_flavor_fails_before_delete_publication():
    connection = _connection()
    connection.capabilities["features"]["flavor.delete"] = {"supported": True}
    outbox = _Outbox()
    service = OperationApplicationService(
        _Repository(connection), outbox, _Inventory(flavor_state=None)
    )
    with pytest.raises(ProviderConnectionNotFoundError):
        await service.create_flavor_operation(
            connection.id,
            idempotency_key="delete-stale",
            correlation_id=uuid.uuid4(),
            request=FlavorDeleteRequest(
                operation_id=uuid.uuid4(),
                provider_connection_id=connection.id,
                provider_resource_id="flavor-1",
            ),
        )
    assert outbox.drafts == []
