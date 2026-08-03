"""CPS-302 inventory batch persistence integration tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from cps.contracts.messages.inventory import InventoryBatchPayload, compute_inventory_checksum
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ConnectionStatus, OperationState
from cps.infrastructure.db.models.inventory import Flavor, Image, Instance
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


def _volume_payload(sync_id: uuid.UUID) -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "volume-1",
            "project_provider_resource_id": "project-1",
            "name": "data",
            "provider_status": "available",
            "size_gib": 20,
            "volume_type_provider_resource_id": "type-1",
            "bootable": False,
            "root": False,
            "encrypted": True,
            "metadata": {"tier": "gold"},
            "availability_zone": "nova",
            "attachments": [{"server_id": "server-1", "device": "/dev/vdb"}],
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "volume",
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
    connection_id = new_uuid7()
    operation_id = new_uuid7()
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
    uow.session.add(
        ProviderConnection(
            id=connection_id,
            provider_id=provider_id,
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


@pytest.mark.asyncio
async def test_volume_inventory_persists_typed_fields_and_project_filter(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["volume"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_volume_payload(sync_id),
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        rows, total = await second.inventory.list_resources(
            "volume",
            offset=0,
            limit=50,
            project_provider_resource_id="project-1",
        )
        assert total == 1
        assert rows[0].size_gib == 20
        assert rows[0].volume_type_provider_resource_id == "type-1"
        assert rows[0].root is False
        assert rows[0].metadata_values == {"tier": "gold"}
        assert rows[0].attachments == [{"server_id": "server-1", "device": "/dev/vdb"}]
        foreign_rows, foreign_total = await second.inventory.list_resources(
            "volume",
            offset=0,
            limit=50,
            project_provider_resource_id="other-project",
        )
        assert foreign_rows == []
        assert foreign_total == 0


@pytest.mark.asyncio
async def test_catalog_inventory_promotes_image_and_flavor_query_fields(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        connection_id, operation_id = await _seed_connection(uow)
        sync = await uow.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image", "flavor"],
        )
        image_item = {
            "provider_resource_id": "image-1",
            "project_provider_resource_id": "project-1",
            "name": "ubuntu",
            "provider_status": "active",
            "visibility": "shared",
            "disk_format": "qcow2",
            "size_bytes": 2_147_483_648,
            "min_disk_gib": 20,
            "min_ram_mib": 2048,
            "checksum": "a" * 32,
            "catalog_approved": True,
            "is_protected": True,
            "container_format": "bare",
            "virtual_size_bytes": 10_737_418_240,
            "tags": ["ubuntu"],
            "properties": {"os_distro": "ubuntu"},
        }
        flavor_item = {
            "provider_resource_id": "flavor-1",
            "name": "medium",
            "vcpus": 4,
            "ram_mib": 8192,
            "root_disk_gib": 80,
            "ephemeral_disk_gib": 20,
            "swap_mib": 1024,
            "is_public": False,
            "enabled": True,
            "catalog_approved": True,
            "extra_specs": {"hw:cpu_policy": "dedicated"},
            "access_project_ids": ["project-1"],
        }
        for resource_type, item in (("image", image_item), ("flavor", flavor_item)):
            batch = InventoryBatchPayload.model_validate(
                {
                    "sync_id": str(sync_id),
                    "resource_type": resource_type,
                    "sequence": 1,
                    "is_last": True,
                    "item_count": 1,
                    "checksum": compute_inventory_checksum([item]),
                    "items": [item],
                }
            )
            await uow.inventory.persist_batch(
                sync=sync,
                message_id=new_uuid7(),
                provider_connection_id=connection_id,
                batch=batch,
            )
        await uow.commit()

    verify = SqlAlchemyUnitOfWork(db_session_factory)
    async with verify:
        image = await verify.session.scalar(select(Image))
        flavor = await verify.session.scalar(select(Flavor))
        assert image is not None
        assert flavor is not None
        assert (image.visibility, image.disk_format, image.size_bytes) == (
            "shared",
            "qcow2",
            2_147_483_648,
        )
        assert (image.min_disk_gib, image.min_ram_mib, image.checksum) == (20, 2048, "a" * 32)
        assert image.provider_attributes == {
            "catalog_approved": True,
            "container_format": "bare",
            "is_protected": True,
            "properties": {"os_distro": "ubuntu"},
            "tags": ["ubuntu"],
            "virtual_size_bytes": 10_737_418_240,
        }
        assert (flavor.vcpus, flavor.ram_mib, flavor.root_disk_gib) == (4, 8192, 80)
        assert flavor.provider_attributes == {
            "access_project_ids": ["project-1"],
            "catalog_approved": True,
            "extra_specs": {"hw:cpu_policy": "dedicated"},
        }
