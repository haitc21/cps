"""CPS-302 inventory batch persistence integration tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from cps.contracts.messages.inventory import InventoryBatchPayload, compute_inventory_checksum
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.enums import ConnectionStatus, OperationState
from cps.infrastructure.db.models.inventory import Instance
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.inventory import (
    InventoryBatchConflictError,
    InventorySyncIncompleteError,
)
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def _payload(sync_id: uuid.UUID, *, name: str = "server") -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "server-1",
            "name": name,
            "provider_status": "ACTIVE",
            "attributes": {"power_state": "RUNNING"},
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "instance",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


async def _seed_connection(uow: SqlAlchemyUnitOfWork) -> tuple[uuid.UUID, uuid.UUID]:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    connection_id = new_uuid7()
    operation_id = new_uuid7()
    uow.session.add(Provider(id=provider_id, name=f"provider-{provider_id}"))
    uow.session.add(
        Credential(
            id=credential_id,
            username_ciphertext=b"u",
            username_nonce=b"u" * 12,
            password_ciphertext=b"p",
            password_nonce=b"p" * 12,
            encryption_key_version="test",
        )
    )
    await uow.session.flush()
    uow.session.add(
        ProviderConnection(
            id=connection_id,
            provider_id=provider_id,
            credential_id=credential_id,
            project_name="demo",
            region_name="RegionOne",
            auth_url="https://keystone.example/v3",
            status=ConnectionStatus.PENDING_VALIDATION,
        )
    )
    await uow.session.flush()
    uow.session.add(
        Operation(
            id=operation_id,
            provider_connection_id=connection_id,
            operation_type="inventory.sync",
            state=OperationState.ACCEPTED,
            request_fingerprint="a" * 64,
            request_payload={},
            correlation_id=new_uuid7(),
        )
    )
    await uow.session.flush()
    return connection_id, operation_id


@pytest.mark.asyncio
async def test_inventory_batch_is_idempotent_and_upserts_by_provider_identity(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    message_id = new_uuid7()
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["instance"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=message_id,
            provider_connection_id=connection_id,
            batch=_payload(sync_id),
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        sync = await second.inventory.get_sync(sync_id)
        assert sync is not None
        duplicate = await second.inventory.persist_batch(
            sync=sync,
            message_id=message_id,
            provider_connection_id=sync.provider_connection_id,
            batch=_payload(sync_id),
        )
        assert duplicate.sequence == 1
        with pytest.raises(InventoryBatchConflictError, match="checksum conflict"):
            await second.inventory.persist_batch(
                sync=sync,
                message_id=new_uuid7(),
                provider_connection_id=sync.provider_connection_id,
                batch=_payload(sync_id, name="different"),
            )
        result = await second.session.execute(select(Instance))
        rows = list(result.scalars())
        assert len(rows) == 1
        assert rows[0].name == "server"
        finalized = await second.inventory.finalize_full_sync(sync_id)
        assert finalized.state == "SUCCEEDED"
        second_operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=second_operation_id,
                provider_connection_id=sync.provider_connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="b" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        incomplete = await second.inventory.create_sync(
            sync_id=new_uuid7(),
            operation_id=second_operation_id,
            provider_connection_id=sync.provider_connection_id,
            sync_type="FULL",
            expected_collections=["volume"],
        )
        with pytest.raises(InventorySyncIncompleteError):
            await second.inventory.finalize_full_sync(incomplete.id)
