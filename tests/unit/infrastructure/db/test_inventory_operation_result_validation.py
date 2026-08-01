"""Regression tests for canonical validation on operation-result inventory persistence."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cps.infrastructure.db.repositories.inventory import (
    InventoryPersistenceError,
    InventoryRepository,
)

pytestmark = pytest.mark.asyncio


async def test_persist_snapshot_result_rejects_nested_secret_value_in_metadata() -> None:
    session = AsyncMock()
    repo = InventoryRepository(session)

    with pytest.raises(InventoryPersistenceError, match="canonical validation"):
        await repo.persist_snapshot_result(
            provider_connection_id=uuid.uuid4(),
            sync_id=None,
            snapshot={
                "provider_resource_id": "snap-secret",
                "name": "checkpoint",
                "metadata": {"config": {"note": "password=leaked-value"}},
            },
        )

    session.execute.assert_not_awaited()


async def test_persist_instance_result_rejects_secret_bearing_attributes() -> None:
    session = AsyncMock()
    repo = InventoryRepository(session)

    with pytest.raises(InventoryPersistenceError, match="canonical validation"):
        await repo.persist_instance_result(
            provider_connection_id=uuid.uuid4(),
            sync_id=None,
            instance={
                "provider_resource_id": "inst-1",
                "name": "web-1",
                "attributes": {"userData": "bootstrap"},
            },
        )

    session.execute.assert_not_awaited()


async def test_persist_snapshot_result_forwards_provider_timestamps_to_upsert() -> None:
    connection_id = uuid.uuid4()
    snapshot_row = SimpleNamespace(id=uuid.uuid4())
    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=snapshot_row))
    repo = InventoryRepository(session)
    repo._upsert_resource = AsyncMock()

    raw = {
        "provider_resource_id": "snap-ts",
        "name": "timed",
        "provider_created_at": "2026-08-01T00:00:00Z",
        "provider_updated_at": "2026-08-01T12:34:56.123456Z",
    }
    await repo.persist_snapshot_result(
        provider_connection_id=connection_id,
        sync_id=uuid.uuid4(),
        snapshot=raw,
    )

    item = repo._upsert_resource.await_args.kwargs["item"]
    assert item["provider_created_at"] == "2026-08-01T00:00:00Z"
    assert item["provider_updated_at"] == "2026-08-01T12:34:56.123456Z"


async def test_persist_instance_result_forwards_provider_timestamps_to_upsert() -> None:
    connection_id = uuid.uuid4()
    instance_row = SimpleNamespace(id=uuid.uuid4())
    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=instance_row))
    repo = InventoryRepository(session)
    repo._upsert_resource = AsyncMock()

    raw = {
        "provider_resource_id": "inst-ts",
        "name": "web-ts",
        "provider_created_at": "2026-08-01T00:00:00Z",
        "provider_updated_at": "2026-08-01T12:34:56.123456Z",
    }
    await repo.persist_instance_result(
        provider_connection_id=connection_id,
        sync_id=uuid.uuid4(),
        instance=raw,
    )

    item = repo._upsert_resource.await_args.kwargs["item"]
    assert item["provider_created_at"] == "2026-08-01T00:00:00Z"
    assert item["provider_updated_at"] == "2026-08-01T12:34:56.123456Z"


async def test_apply_volume_attachment_result_rejects_non_object_resource() -> None:
    instance_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="inst-1")
    volume_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="vol-1")
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[instance_row, volume_row])
    repo = InventoryRepository(session)

    with pytest.raises(InventoryPersistenceError, match="canonical validation"):
        await repo.apply_volume_attachment_result(
            provider_connection_id=uuid.uuid4(),
            operation="attach",
            instance_provider_resource_id="inst-1",
            volume_provider_resource_id="vol-1",
            resource="invalid-string",
        )

    session.merge.assert_not_awaited()


async def test_apply_volume_attachment_result_rejects_secret_bearing_resource() -> None:
    instance_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="inst-1")
    volume_row = SimpleNamespace(id=uuid.uuid4(), provider_resource_id="vol-1")
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[instance_row, volume_row])
    repo = InventoryRepository(session)

    with pytest.raises(InventoryPersistenceError, match="canonical validation"):
        await repo.apply_volume_attachment_result(
            provider_connection_id=uuid.uuid4(),
            operation="attach",
            instance_provider_resource_id="inst-1",
            volume_provider_resource_id="vol-1",
            resource={"device": "Bearer lettersonlycredential"},
        )

    session.merge.assert_not_awaited()


async def test_upsert_resource_ownership_conflict_is_redacted() -> None:
    from cps.infrastructure.db.models.inventory import Image

    session = AsyncMock()
    repo = InventoryRepository(session)

    with pytest.raises(
        InventoryPersistenceError,
        match="conflicting ownership sources",
    ) as exc_info:
        await repo._upsert_resource(
            model=Image,
            provider_connection_id=uuid.uuid4(),
            sync_id=uuid.uuid4(),
            item={
                "provider_resource_id": "img-1",
                "name": "owned",
                "project_provider_resource_id": "project-a",
                "attributes": {"project_id": "project-b"},
            },
        )

    message = str(exc_info.value)
    assert "project-a" not in message
    assert "project-b" not in message
