from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import IdempotencyKeyReusedError
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.flavor_operations import FlavorCreateRequest, FlavorDeleteRequest
from cps.contracts.messages.types import OPERATION_COMPLETED
from cps.domain.operations.service import EVENT_TYPE_LATE_RESULT
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus
from cps.infrastructure.db.models.inventory import Flavor, Instance, Project
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.infrastructure.messaging.inbox_consumer import DeliveryProcessingRecord, EventInboxConsumer
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher

pytestmark = pytest.mark.integration


async def _seed_provider(uow: SqlAlchemyUnitOfWork):
    provider_id, system_id, project_connection_id = new_uuid7(), new_uuid7(), new_uuid7()
    uow.session.add(
        Provider(
            id=provider_id,
            name=f"provider-{provider_id}",
            username_ciphertext=b"u",
            username_nonce=b"u" * 12,
            password_ciphertext=b"p",
            password_nonce=b"p" * 12,
            encryption_key_version="test",
        )
    )
    await uow.session.flush()
    for connection_id, scope in (
        (system_id, ConnectionScopeKind.SYSTEM),
        (project_connection_id, ConnectionScopeKind.PROJECT),
    ):
        uow.session.add(
            ProviderConnection(
                id=connection_id,
                provider_id=provider_id,
                project_name=f"project-{connection_id}",
                region_name="RegionOne",
                auth_url="https://keystone.example/v3",
                scope_kind=scope,
                status=ConnectionStatus.VALID,
                capabilities={
                    "features": {
                        "flavor.create": {"supported": True},
                        "flavor.delete": {"supported": True},
                    }
                },
            )
        )
    await uow.session.flush()
    return provider_id, system_id, project_connection_id


@pytest.mark.asyncio
async def test_provider_global_projects_casefold_name_and_dependency_guards(db_session_factory):
    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        provider_id, system_id, project_connection_id = await _seed_provider(uow)
        uow.session.add(
            Project(
                id=new_uuid7(),
                provider_id=provider_id,
                provider_connection_id=project_connection_id,
                provider_resource_id="project-1",
                name="project",
                lifecycle_state="ACTIVE",
            )
        )
        uow.session.add(
            Flavor(
                id=new_uuid7(),
                provider_connection_id=system_id,
                provider_resource_id="flavor-1",
                name="Small",
                lifecycle_state="ACTIVE",
                enabled=True,
                is_public=False,
                provider_attributes={"catalog_approved": False},
            )
        )
        uow.session.add(
            Instance(
                id=new_uuid7(),
                provider_connection_id=project_connection_id,
                provider_resource_id="instance-1",
                name="instance",
                lifecycle_state="ACTIVE",
                flavor_provider_resource_id="flavor-1",
            )
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        assert await uow.inventory.project_provider_ids_belong_to_provider(
            provider_id, ["project-1"]
        )
        assert await uow.inventory.live_flavor_name_exists_case_insensitive(system_id, "small")
        assert await uow.inventory.flavor_is_used_on_provider(provider_id, "flavor-1")
        assert await uow.inventory.flavor_mutation_state(system_id, "flavor-1") == (
            False,
            False,
        )


@pytest.mark.asyncio
async def test_flavor_projection_preserves_approval_and_confirmed_delete_tombstones(
    db_session_factory,
):
    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        _provider_id, system_id, _project_connection_id = await _seed_provider(uow)
        await uow.inventory.persist_flavor_result(
            provider_connection_id=system_id,
            flavor={
                "provider_resource_id": "flavor-new",
                "name": "new",
                "vcpus": 2,
                "ram_mib": 2048,
                "root_disk_gib": 20,
                "ephemeral_disk_gib": 0,
                "swap_mib": 0,
                "is_public": True,
                "access_project_ids": [],
                "extra_specs": {"hw:cpu_policy": "shared"},
            },
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        row = await uow.session.scalar(
            select(Flavor).where(Flavor.provider_resource_id == "flavor-new")
        )
        assert row is not None
        assert row.provider_attributes["catalog_approved"] is False
        assert row.ram_mib == 2048
        assert await uow.inventory.mark_resource_deleted("flavor", system_id, "flavor-new")
        await uow.commit()

    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        row = await uow.session.scalar(
            select(Flavor).where(Flavor.provider_resource_id == "flavor-new")
        )
        assert row is not None and row.lifecycle_state == "DELETED"


@pytest.mark.asyncio
async def test_concurrent_cross_operation_key_creates_one_operation_and_outbox(
    db_session_factory,
):
    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        _provider_id, system_id, _project_connection_id = await _seed_provider(uow)
        uow.session.add(
            Flavor(
                id=new_uuid7(),
                provider_connection_id=system_id,
                provider_resource_id="flavor-race",
                name="existing",
                lifecycle_state="ACTIVE",
                enabled=True,
                is_public=True,
                provider_attributes={"catalog_approved": False},
            )
        )
        await uow.commit()

    async def invoke(request):
        async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
            service = OperationApplicationService(uow.operations, uow.outbox, uow.inventory)
            try:
                result = await service.create_flavor_operation(
                    system_id,
                    idempotency_key="cross-operation-race",
                    correlation_id=new_uuid7(),
                    request=request,
                )
                await uow.commit()
                return result
            except IdempotencyKeyReusedError:
                return None

    results = await asyncio.gather(
        invoke(
            FlavorCreateRequest(
                operation_id=new_uuid7(),
                provider_connection_id=system_id,
                name="created",
                vcpus=1,
                ram_mib=512,
                root_disk_gib=0,
                is_public=True,
            )
        ),
        invoke(
            FlavorDeleteRequest(
                operation_id=new_uuid7(),
                provider_connection_id=system_id,
                provider_resource_id="flavor-race",
            )
        ),
    )
    assert sum(result is not None for result in results) == 1
    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        from cps.infrastructure.db.models.operations import Operation
        from cps.infrastructure.db.models.outbox_messages import OutboxMessage

        assert await uow.session.scalar(select(func.count(Operation.id))) == 1
        assert await uow.session.scalar(select(func.count(OutboxMessage.id))) == 1


@pytest.mark.asyncio
async def test_real_inbox_duplicate_and_late_flavor_completion_are_immutable(
    db_session_factory,
):
    operation_id = new_uuid7()
    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        provider_id, system_id, _ = await _seed_provider(uow)
        uow.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=system_id,
                operation_type="openstack.flavor.create",
                state="RUNNING",
                request_fingerprint="a" * 64,
                request_payload={"provider_resource_id": None},
                correlation_id=new_uuid7(),
            )
        )
        await uow.commit()

    def envelope(*, message_id, ram_mib):
        return MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": OPERATION_COMPLETED,
                "schema_version": "1.0",
                "occurred_at": datetime.now(UTC),
                "correlation_id": new_uuid7(),
                "operation_id": operation_id,
                "provider_id": provider_id,
                "provider_connection_id": system_id,
                "payload": {
                    "result": {
                        "schema_version": "1.0",
                        "operation_id": str(operation_id),
                        "resource_type": "flavor",
                        "operation": "create",
                        "state": "SUCCEEDED",
                        "provider_resource_id": "flavor-inbox",
                        "resource": {
                            "provider_resource_id": "flavor-inbox",
                            "name": "inbox",
                            "vcpus": 1,
                            "ram_mib": ram_mib,
                            "root_disk_gib": 0,
                            "ephemeral_disk_gib": 0,
                            "swap_mib": 0,
                            "is_public": True,
                            "access_project_ids": [],
                            "extra_specs": {},
                        },
                        "error": None,
                    }
                },
            }
        )

    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=AsyncMock(),
        session_factory=db_session_factory,
    )
    first = envelope(message_id=new_uuid7(), ram_mib=512)
    await consumer._process_inbox(first, DeliveryProcessingRecord())
    duplicate = await consumer._process_inbox(first, DeliveryProcessingRecord())
    assert duplicate.duplicate is True
    await consumer._process_inbox(
        envelope(message_id=new_uuid7(), ram_mib=4096), DeliveryProcessingRecord()
    )

    async with SqlAlchemyUnitOfWork(db_session_factory) as uow:
        operation = await uow.operations.get_operation(operation_id)
        flavor = await uow.session.scalar(
            select(Flavor).where(Flavor.provider_resource_id == "flavor-inbox")
        )
        late_count = await uow.session.scalar(
            select(func.count(OperationEvent.id)).where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_LATE_RESULT,
            )
        )
        assert operation is not None and operation.state.value == "SUCCEEDED"
        assert flavor is not None and flavor.ram_mib == 512
        assert late_count == 1
