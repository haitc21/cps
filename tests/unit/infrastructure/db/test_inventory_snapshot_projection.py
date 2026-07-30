"""Unit tests for snapshot create result projection in inventory repository."""

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


async def test_persist_snapshot_result_upserts_typed_fields() -> None:
    connection_id = uuid.uuid4()
    snapshot_row = SimpleNamespace(id=uuid.uuid4())
    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=snapshot_row))
    repo = InventoryRepository(session)
    repo._upsert_resource = AsyncMock()

    snapshot = {
        "provider_resource_id": "snap-1",
        "name": "before-upgrade",
        "provider_status": "available",
        "project_provider_resource_id": "project-1",
        "volume_provider_resource_id": "volume-1",
        "snapshot_size_gib": 20,
        "metadata": {"purpose": "release"},
        "attributes": {"description": "checkpoint"},
    }

    row = await repo.persist_snapshot_result(
        provider_connection_id=connection_id,
        sync_id=None,
        snapshot=snapshot,
    )

    assert row is snapshot_row
    repo._upsert_resource.assert_awaited_once()
    kwargs = repo._upsert_resource.await_args.kwargs
    assert kwargs["model"].__tablename__ == "volume_snapshots"
    assert kwargs["provider_connection_id"] == connection_id
    assert kwargs["item"]["provider_resource_id"] == "snap-1"
    assert kwargs["item"]["name"] == "before-upgrade"
    assert kwargs["item"]["provider_status"] == "available"
    assert kwargs["item"]["project_provider_resource_id"] == "project-1"
    assert kwargs["item"]["volume_provider_resource_id"] == "volume-1"
    assert kwargs["item"]["snapshot_size_gib"] == 20
    assert kwargs["item"]["metadata"] == {"purpose": "release"}
    assert kwargs["item"]["attributes"] == {"description": "checkpoint"}


async def test_persist_snapshot_result_maps_size_from_attributes() -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock(
        scalar_one=MagicMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    )
    repo = InventoryRepository(session)
    repo._upsert_resource = AsyncMock()

    await repo.persist_snapshot_result(
        provider_connection_id=uuid.uuid4(),
        sync_id=uuid.uuid4(),
        snapshot={
            "provider_resource_id": "snap-2",
            "name": "mapped",
            "attributes": {
                "volume_id": "volume-2",
                "size": 10,
                "metadata": {"tier": "gold"},
            },
        },
    )

    item = repo._upsert_resource.await_args.kwargs["item"]
    assert item["volume_provider_resource_id"] is None
    assert item["snapshot_size_gib"] is None
    assert item["metadata"] == {"tier": "gold"}
    assert item["attributes"]["volume_id"] == "volume-2"


@pytest.mark.parametrize(
    "snapshot",
    [{}, {"provider_resource_id": "snap-3"}, {"name": "only-name"}],
)
async def test_persist_snapshot_result_rejects_invalid_identity(snapshot: dict[str, str]) -> None:
    repo = InventoryRepository(AsyncMock())
    repo._upsert_resource = AsyncMock()

    with pytest.raises(InventoryPersistenceError, match="snapshot result identity is invalid"):
        await repo.persist_snapshot_result(
            provider_connection_id=uuid.uuid4(),
            sync_id=None,
            snapshot=snapshot,
        )

    repo._upsert_resource.assert_not_awaited()
