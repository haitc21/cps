"""Read-only curated catalog API behavior."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cps.api.routers.catalog import list_catalog
from cps.api.schemas.catalog import CatalogResourceType


@pytest.mark.parametrize(
    "resource_type",
    [
        CatalogResourceType.AVAILABILITY_ZONE,
        CatalogResourceType.VOLUME_TYPE,
    ],
)
@pytest.mark.asyncio
async def test_new_catalog_types_query_inventory(resource_type) -> None:
    inventory = SimpleNamespace(
        list_catalog_resources=AsyncMock(return_value=([], 0)),
    )

    response = await list_catalog(
        connection_id=uuid.uuid4(),
        resource_type=resource_type,
        pagination=SimpleNamespace(offset=0, limit=50, page=1),
        uow=SimpleNamespace(inventory=inventory),
    )

    inventory.list_catalog_resources.assert_awaited_once()
    assert response.data is not None
    assert response.data.total == 0
    assert response.data.page == 1
