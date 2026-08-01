"""CPS-302 inventory batch persistence integration tests."""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from cps.contracts.messages.inventory import InventoryBatchPayload, compute_inventory_checksum
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ConnectionStatus, OperationState
from cps.infrastructure.db.models.inventory import Instance, Project
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


async def _seed_project(
    uow: SqlAlchemyUnitOfWork,
    *,
    provider_id: uuid.UUID,
    connection_id: uuid.UUID,
    provider_resource_id: str = "project-1",
) -> uuid.UUID:
    project_id = new_uuid7()
    uow.session.add(
        Project(
            id=project_id,
            provider_connection_id=connection_id,
            provider_id=provider_id,
            provider_resource_id=provider_resource_id,
            name=f"project-{provider_resource_id}",
            lifecycle_state="ACTIVE",
        )
    )
    await uow.session.flush()
    return project_id


async def _provider_id_for_connection(
    uow: SqlAlchemyUnitOfWork, connection_id: uuid.UUID
) -> uuid.UUID:
    provider_id = await uow.session.scalar(
        select(ProviderConnection.provider_id).where(ProviderConnection.id == connection_id)
    )
    assert provider_id is not None
    return provider_id


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


def _image_payload(
    sync_id: uuid.UUID,
    *,
    approved: bool = True,
    name: str = "ubuntu",
) -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "img-1",
            "name": name,
            "provider_status": "active",
            "project_provider_resource_id": "project-1",
            "visibility": "public",
            "size_bytes": 1_073_741_824,
            "min_disk_gib": 20,
            "min_ram_mib": 512,
            "disk_format": "qcow2",
            "checksum": "abc123",
            "attributes": {
                "catalog_approved": approved,
                "container_format": "bare",
            },
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


def _flavor_payload(sync_id: uuid.UUID, *, approved: bool = True) -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "flv-1",
            "name": "m1.small",
            "provider_status": "active",
            "vcpus": 1,
            "ram_mib": 2048,
            "root_disk_gib": 20,
            "is_public": True,
            "enabled": True,
            "attributes": {"catalog_approved": approved},
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "flavor",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


@pytest.mark.asyncio
async def test_image_catalog_persists_typed_fields_and_filters(db_session_factory) -> None:
    sync_id = new_uuid7()
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id),
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        rows, total = await second.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=50,
            name="ubuntu",
            visibility="public",
            disk_format="qcow2",
            owner_project_id="project-1",
            size_min_bytes=1_000_000,
            size_max_bytes=2_000_000_000,
            min_disk_gib=10,
            min_ram_mib=256,
            approved=True,
        )
        assert total == 1
        row = rows[0]
        assert row.disk_format == "qcow2"
        assert row.visibility == "public"
        assert row.size_bytes == 1_073_741_824
        assert row.provider_attributes["catalog_approved"] is True

        detail = await second.inventory.get_catalog_resource(
            "image",
            connection_id,
            row.id,
            approved=True,
        )
        assert detail is not None
        assert detail.name == "ubuntu"


@pytest.mark.asyncio
async def test_image_upsert_refreshes_all_typed_fields_on_conflict(db_session_factory) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id, name="ubuntu-v1"),
        )
        await first.commit()

    refresh_sync_id = new_uuid7()
    changed_items = [
        {
            "provider_resource_id": "img-1",
            "name": "ubuntu-v2",
            "provider_status": "active",
            "project_provider_resource_id": "project-2",
            "visibility": "community",
            "size_bytes": 2_147_483_648,
            "min_disk_gib": 40,
            "min_ram_mib": 1024,
            "disk_format": "raw",
            "checksum": "def456",
            "attributes": {
                "catalog_approved": True,
                "container_format": "docker",
            },
        }
    ]
    changed_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(changed_items),
            "items": changed_items,
        }
    )

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="b" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        sync = await second.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await second.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=changed_batch,
        )
        await second.commit()

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-v2",
        )
        assert total == 1
        row = rows[0]
        assert row.name == "ubuntu-v2"
        assert row.project_provider_resource_id == "project-2"
        assert row.project_id is None
        assert row.visibility == "community"
        assert row.size_bytes == 2_147_483_648
        assert row.min_disk_gib == 40
        assert row.min_ram_mib == 1024
        assert row.disk_format == "raw"
        assert row.checksum == "def456"
        assert row.provider_attributes["container_format"] == "docker"


@pytest.mark.asyncio
async def test_image_refresh_without_ownership_preserves_project_linkage(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        seeded_project_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id, name="ubuntu-owned"),
        )
        await first.commit()

    refresh_sync_id = new_uuid7()
    refresh_items = [
        {
            "provider_resource_id": "img-1",
            "name": "ubuntu-refreshed",
            "provider_status": "active",
            "visibility": "public",
            "size_bytes": 2_000_000_000,
            "min_disk_gib": 20,
            "min_ram_mib": 512,
            "disk_format": "qcow2",
            "checksum": "refresh123",
            "attributes": {"catalog_approved": True, "container_format": "bare"},
        }
    ]
    refresh_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(refresh_items),
            "items": refresh_items,
        }
    )

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="c" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        sync = await second.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await second.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=refresh_batch,
        )
        await second.commit()

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-refreshed",
        )
        assert total == 1
        row = rows[0]
        assert row.name == "ubuntu-refreshed"
        assert row.project_provider_resource_id == "project-1"
        assert row.project_id == seeded_project_id
        assert row.visibility == "public"
        assert row.size_bytes == 2_000_000_000
        assert row.checksum == "refresh123"


@pytest.mark.asyncio
async def test_image_refresh_with_changed_unresolved_owner_clears_project_id(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        seeded_project_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id, name="ubuntu-owned"),
        )
        await first.commit()

    after_first = SqlAlchemyUnitOfWork(db_session_factory)
    async with after_first:
        rows, _ = await after_first.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-owned",
        )
        assert len(rows) == 1
        assert rows[0].project_id == seeded_project_id
        assert rows[0].project_provider_resource_id == "project-1"

    refresh_sync_id = new_uuid7()
    refresh_items = [
        {
            "provider_resource_id": "img-1",
            "name": "ubuntu-unresolved-owner",
            "provider_status": "active",
            "project_provider_resource_id": "unknown-project",
            "visibility": "public",
            "size_bytes": 2_000_000_000,
            "attributes": {"catalog_approved": True},
        }
    ]
    refresh_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(refresh_items),
            "items": refresh_items,
        }
    )

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="d" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        sync = await second.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await second.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=refresh_batch,
        )
        await second.commit()

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-unresolved-owner",
        )
        assert total == 1
        row = rows[0]
        assert row.name == "ubuntu-unresolved-owner"
        assert row.project_provider_resource_id == "unknown-project"
        assert row.project_id is None


@pytest.mark.asyncio
async def test_image_refresh_with_unchanged_owner_preserves_resolved_project_id(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        seeded_project_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id, name="ubuntu-stable-owner"),
        )
        await first.session.execute(
            sa.update(Project)
            .where(Project.id == seeded_project_id)
            .values(lifecycle_state="DELETED")
        )
        await first.commit()

    refresh_sync_id = new_uuid7()
    refresh_items = [
        {
            "provider_resource_id": "img-1",
            "name": "ubuntu-stable-owner-v2",
            "provider_status": "active",
            "project_provider_resource_id": "project-1",
            "visibility": "public",
            "size_bytes": 2_000_000_000,
            "attributes": {"catalog_approved": True},
        }
    ]
    refresh_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(refresh_items),
            "items": refresh_items,
        }
    )

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="e" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        sync = await second.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await second.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=refresh_batch,
        )
        await second.commit()

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-stable-owner-v2",
        )
        assert total == 1
        row = rows[0]
        assert row.project_provider_resource_id == "project-1"
        assert row.project_id == seeded_project_id


@pytest.mark.asyncio
async def test_image_refresh_with_resolved_owner_updates_linkage(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        project_one_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        project_two_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-2",
        )
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=_image_payload(sync_id, name="ubuntu-project-one"),
        )
        await first.commit()

    after_first = SqlAlchemyUnitOfWork(db_session_factory)
    async with after_first:
        rows, _ = await after_first.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-project-one",
        )
        assert len(rows) == 1
        assert rows[0].project_id == project_one_id

    refresh_sync_id = new_uuid7()
    refresh_items = [
        {
            "provider_resource_id": "img-1",
            "name": "ubuntu-project-two",
            "provider_status": "active",
            "project_provider_resource_id": "project-2",
            "visibility": "public",
            "size_bytes": 2_000_000_000,
            "attributes": {"catalog_approved": True},
        }
    ]
    refresh_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(refresh_items),
            "items": refresh_items,
        }
    )

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        operation_id = new_uuid7()
        second.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="f" * 64,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await second.session.flush()
        sync = await second.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await second.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=refresh_batch,
        )
        await second.commit()

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=10,
            name="ubuntu-project-two",
        )
        assert total == 1
        row = rows[0]
        assert row.project_provider_resource_id == "project-2"
        assert row.project_id == project_two_id


def _snapshot_payload(sync_id: uuid.UUID, *, name: str = "snap-data") -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "snap-1",
            "project_provider_resource_id": "project-1",
            "name": name,
            "provider_status": "available",
            "volume_provider_resource_id": "volume-1",
            "snapshot_size_gib": 20,
            "metadata": {"tier": "gold"},
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "volume-snapshot",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


def _keypair_payload(sync_id: uuid.UUID, *, name: str = "my-key") -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "keypair-1",
            "project_provider_resource_id": "project-1",
            "name": name,
            "attributes": {
                "fingerprint": "aa:bb:cc",
                "type": "ssh",
                "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB",
            },
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "keypair",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


def _quota_payload(sync_id: uuid.UUID, *, name: str = "instances") -> InventoryBatchPayload:
    items = [
        {
            "provider_resource_id": "quota-1",
            "project_provider_resource_id": "project-1",
            "name": name,
            "attributes": {
                "service": "nova",
                "resource_name": "instances",
                "limit_value": 10,
                "in_use": 2,
            },
        }
    ]
    return InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "quota",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )


async def _persist_refresh_batch(
    db_session_factory,
    *,
    connection_id: uuid.UUID,
    resource_type: str,
    refresh_items: list[dict[str, object]],
) -> None:
    refresh_sync_id = new_uuid7()
    refresh_batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(refresh_sync_id),
            "resource_type": resource_type,
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": len(refresh_items),
            "checksum": compute_inventory_checksum(refresh_items),
            "items": refresh_items,
        }
    )
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        operation_id = new_uuid7()
        uow.session.add(
            Operation(
                id=operation_id,
                provider_connection_id=connection_id,
                operation_type="inventory.sync",
                state=OperationState.ACCEPTED,
                request_fingerprint="refresh" + "0" * 57,
                request_payload={},
                correlation_id=new_uuid7(),
            )
        )
        await uow.session.flush()
        sync = await uow.inventory.create_sync(
            sync_id=refresh_sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=[resource_type],
        )
        await uow.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=refresh_batch,
        )
        await uow.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource_type", "initial_batch_factory", "refresh_item", "list_name"),
    [
        (
            "volume",
            lambda sync_id: _volume_payload(sync_id),
            {
                "provider_resource_id": "volume-1",
                "name": "data-refreshed",
                "provider_status": "available",
                "size_gib": 30,
                "volume_type_provider_resource_id": "type-1",
                "bootable": False,
                "metadata": {"tier": "silver"},
            },
            "data-refreshed",
        ),
        (
            "volume-snapshot",
            lambda sync_id: _snapshot_payload(sync_id),
            {
                "provider_resource_id": "snap-1",
                "name": "snap-refreshed",
                "provider_status": "available",
                "volume_provider_resource_id": "volume-1",
                "snapshot_size_gib": 25,
                "metadata": {"tier": "silver"},
            },
            "snap-refreshed",
        ),
        (
            "keypair",
            lambda sync_id: _keypair_payload(sync_id),
            {
                "provider_resource_id": "keypair-1",
                "name": "my-key-refreshed",
                "attributes": {
                    "fingerprint": "dd:ee:ff",
                    "type": "ssh",
                    "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB",
                },
            },
            "my-key-refreshed",
        ),
        (
            "quota",
            lambda sync_id: _quota_payload(sync_id),
            {
                "provider_resource_id": "quota-1",
                "name": "instances-refreshed",
                "attributes": {
                    "service": "nova",
                    "resource_name": "instances",
                    "limit_value": 20,
                    "in_use": 5,
                },
            },
            "instances-refreshed",
        ),
    ],
    ids=["volume", "volume-snapshot", "keypair", "quota"],
)
async def test_project_scoped_refresh_without_ownership_preserves_project_linkage(
    db_session_factory,
    resource_type: str,
    initial_batch_factory,
    refresh_item: dict[str, object],
    list_name: str,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    seeded_project_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        seeded_project_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=[resource_type],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=initial_batch_factory(sync_id),
        )
        await first.commit()

    await _persist_refresh_batch(
        db_session_factory,
        connection_id=connection_id,
        resource_type=resource_type,
        refresh_items=[refresh_item],
    )

    verify = SqlAlchemyUnitOfWork(db_session_factory)
    async with verify:
        rows, total = await verify.inventory.list_resources(
            resource_type,
            offset=0,
            limit=10,
            provider_connection_id=connection_id,
            name=list_name,
        )
        assert total == 1
        row = rows[0]
        assert row.project_provider_resource_id == "project-1"
        assert row.project_id == seeded_project_id


@pytest.mark.asyncio
async def test_volume_refresh_with_resolved_owner_updates_linkage(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    connection_id: uuid.UUID
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        provider_id = await _provider_id_for_connection(first, connection_id)
        project_one_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-1",
        )
        project_two_id = await _seed_project(
            first,
            provider_id=provider_id,
            connection_id=connection_id,
            provider_resource_id="project-2",
        )
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

    after_first = SqlAlchemyUnitOfWork(db_session_factory)
    async with after_first:
        rows, _ = await after_first.inventory.list_resources(
            "volume",
            offset=0,
            limit=10,
            provider_connection_id=connection_id,
        )
        assert len(rows) == 1
        assert rows[0].project_id == project_one_id

    await _persist_refresh_batch(
        db_session_factory,
        connection_id=connection_id,
        resource_type="volume",
        refresh_items=[
            {
                "provider_resource_id": "volume-1",
                "project_provider_resource_id": "project-2",
                "name": "data-moved",
                "provider_status": "available",
                "size_gib": 40,
                "volume_type_provider_resource_id": "type-1",
            }
        ],
    )

    third = SqlAlchemyUnitOfWork(db_session_factory)
    async with third:
        rows, total = await third.inventory.list_resources(
            "volume",
            offset=0,
            limit=10,
            provider_connection_id=connection_id,
            name="data-moved",
        )
        assert total == 1
        row = rows[0]
        assert row.project_provider_resource_id == "project-2"
        assert row.project_id == project_two_id


@pytest.mark.asyncio
async def test_catalog_list_orders_by_name_then_id(db_session_factory) -> None:
    sync_id = new_uuid7()
    items = [
        {
            "provider_resource_id": "img-b",
            "name": "beta",
            "attributes": {"catalog_approved": True},
        },
        {
            "provider_resource_id": "img-a",
            "name": "alpha",
            "attributes": {"catalog_approved": True},
        },
    ]
    batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 2,
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=batch,
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        rows, _total = await second.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=50,
            approved=True,
        )
        assert [row.name for row in rows] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_member_public_catalog_filters_use_expression_indexes(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    target_disk_format = "qcow2"
    target_visibility = "public"
    items = []
    for index in range(500):
        disk_format = target_disk_format if index < 100 else "raw"
        visibility = target_visibility if index % 2 == 0 else "community"
        items.append(
            {
                "provider_resource_id": f"img-public-{index:03d}",
                "name": f"public-{index:03d}",
                "provider_status": "active",
                "visibility": visibility,
                "disk_format": disk_format,
                "attributes": {"catalog_approved": True},
            }
        )
    batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": len(items),
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=batch,
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        rows, total = await second.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=50,
            approved=True,
            visibility=target_visibility,
            disk_format=target_disk_format,
            member_public_catalog_only=True,
        )
        assert total == 50
        assert len(rows) == 50
        assert all(row.disk_format == target_disk_format for row in rows)
        assert all(row.visibility == target_visibility for row in rows)

        await second.session.execute(sa.text("ANALYZE images"))
        await second.session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        explain_sql = """
            EXPLAIN (FORMAT JSON)
            SELECT id FROM images
            WHERE provider_connection_id = :connection_id
              AND lifecycle_state <> 'DELETED'
              AND visibility = :visibility
              AND disk_format = :disk_format
              AND provider_attributes @> '{"catalog_approved": true}'::jsonb
        """
        result = await second.session.execute(
            sa.text(explain_sql),
            {
                "connection_id": connection_id,
                "visibility": target_visibility,
                "disk_format": target_disk_format,
            },
        )
        plan_text = json.dumps(result.scalar_one())
        assert "ix_images_catalog_filters" in plan_text


@pytest.mark.asyncio
async def test_catalog_name_filter_escapes_like_wildcards(db_session_factory) -> None:
    sync_id = new_uuid7()
    items = [
        {
            "provider_resource_id": "img-literal",
            "name": "100%_done",
            "provider_status": "active",
            "visibility": "public",
            "attributes": {"catalog_approved": True},
        },
        {
            "provider_resource_id": "img-wildcard",
            "name": "100X_done",
            "provider_status": "active",
            "visibility": "public",
            "attributes": {"catalog_approved": True},
        },
    ]
    batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": len(items),
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=batch,
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        rows, total = await second.inventory.list_catalog_resources(
            "image",
            connection_id,
            offset=0,
            limit=50,
            name="100%_done",
            approved=True,
        )
        assert total == 1
        assert rows[0].name == "100%_done"


@pytest.mark.asyncio
async def test_member_scope_queries_use_jsonb_expression_indexes(
    db_session_factory,
) -> None:
    sync_id = new_uuid7()
    project_scope = "project-scope-1"
    items = []
    for index in range(500):
        items.append(
            {
                "provider_resource_id": f"img-shared-{index:03d}",
                "name": f"shared-{index:03d}",
                "provider_status": "active",
                "visibility": "shared",
                "attributes": {
                    "catalog_approved": True,
                    "member_project_ids": [project_scope],
                },
            }
        )
    batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": len(items),
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=["image"],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=batch,
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        index_rows = await second.session.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'images' AND indexname = 'ix_images_catalog_member_projects'"
            )
        )
        assert index_rows.scalar_one_or_none() == "ix_images_catalog_member_projects"

        await second.session.execute(sa.text("ANALYZE images"))
        await second.session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        explain_sql = """
            EXPLAIN (FORMAT JSON)
            SELECT id FROM images
            WHERE provider_connection_id = :connection_id
              AND lifecycle_state = 'ACTIVE'
              AND visibility = 'shared'
              AND provider_attributes @> '{"catalog_approved": true}'::jsonb
              AND provider_attributes -> 'member_project_ids' @> CAST(:member_json AS jsonb)
        """
        result = await second.session.execute(
            sa.text(explain_sql),
            {
                "connection_id": connection_id,
                "member_json": f'["{project_scope}"]',
            },
        )
        plan = result.scalar_one()
        plan_text = json.dumps(plan)
        assert "ix_images_catalog_member_projects" in plan_text


@pytest.mark.parametrize(
    ("resource_type", "table_name", "index_name", "collection", "item_factory"),
    [
        (
            "image",
            "images",
            "ix_images_catalog_status",
            "image",
            lambda index: {
                "provider_resource_id": f"img-status-{index}",
                "name": f"status-{index}",
                "provider_status": "active" if index % 2 == 0 else "deactivated",
                "visibility": "public",
                "attributes": {"catalog_approved": True},
            },
        ),
        (
            "flavor",
            "flavors",
            "ix_flavors_catalog_status",
            "flavor",
            lambda index: {
                "provider_resource_id": f"flv-status-{index}",
                "name": f"status-{index}",
                "provider_status": "active" if index % 2 == 0 else "disabled",
                "is_public": True,
                "enabled": True,
                "attributes": {"catalog_approved": True},
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_catalog_status_filter_uses_expression_indexes(
    db_session_factory,
    resource_type: str,
    table_name: str,
    index_name: str,
    collection: str,
    item_factory: object,
) -> None:
    sync_id = new_uuid7()
    target_status = "active"
    items = [item_factory(index) for index in range(500)]  # type: ignore[operator]
    batch = InventoryBatchPayload.model_validate(
        {
            "sync_id": str(sync_id),
            "resource_type": resource_type,
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": len(items),
            "checksum": compute_inventory_checksum(items),
            "items": items,
        }
    )
    first = SqlAlchemyUnitOfWork(db_session_factory)
    async with first:
        connection_id, operation_id = await _seed_connection(first)
        sync = await first.inventory.create_sync(
            sync_id=sync_id,
            operation_id=operation_id,
            provider_connection_id=connection_id,
            sync_type="FULL",
            expected_collections=[collection],
        )
        await first.inventory.persist_batch(
            sync=sync,
            message_id=new_uuid7(),
            provider_connection_id=connection_id,
            batch=batch,
        )
        await first.commit()

    second = SqlAlchemyUnitOfWork(db_session_factory)
    async with second:
        list_kwargs: dict[str, object] = {
            "offset": 0,
            "limit": 50,
            "approved": True,
            "status": target_status,
        }
        if resource_type == "image":
            list_kwargs["member_public_catalog_only"] = True
        rows, total = await second.inventory.list_catalog_resources(
            resource_type,
            connection_id,
            **list_kwargs,
        )
        assert total == 250
        assert len(rows) == 50
        assert all(
            row.provider_status and row.provider_status.lower() == target_status for row in rows
        )

        await second.session.execute(sa.text(f"ANALYZE {table_name}"))
        await second.session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        explain_sql = f"""
            EXPLAIN (FORMAT JSON)
            SELECT id FROM {table_name}
            WHERE provider_connection_id = :connection_id
              AND lifecycle_state <> 'DELETED'
              AND lower(provider_status) = :status
              AND provider_attributes @> '{{"catalog_approved": true}}'::jsonb
        """
        result = await second.session.execute(
            sa.text(explain_sql),
            {"connection_id": connection_id, "status": target_status},
        )
        plan_text = json.dumps(result.scalar_one())
        assert index_name in plan_text
