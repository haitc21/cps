"""Read-only curated catalog API behavior."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cps.api.routers.catalog import get_member_catalog, list_catalog, list_member_catalog
from cps.api.routers.inventory import list_inventory
from cps.api.schemas.catalog import CatalogMemberResourceType, CatalogResourceType
from cps.contracts.errors import ResourceNotFoundError


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


@pytest.mark.asyncio
async def test_member_catalog_forces_curated_projection_without_provider_attributes() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=uuid.uuid4(),
        provider_resource_id="image-1",
        name="ubuntu",
        provider_status="active",
        visibility="public",
        size_bytes=2_147_483_648,
        min_disk_gib=20,
        min_ram_mib=2048,
        disk_format="qcow2",
        checksum="a" * 32,
        provider_attributes={"catalog_approved": True, "properties": {"os_distro": "ubuntu"}},
    )
    inventory = SimpleNamespace(
        list_catalog_resources=AsyncMock(return_value=([row], 1)),
    )

    response = await list_member_catalog(
        connection_id=row.provider_connection_id,
        resource_type=CatalogMemberResourceType.IMAGE,
        pagination=SimpleNamespace(offset=0, limit=50, page=1),
        uow=SimpleNamespace(inventory=inventory),
    )

    inventory.list_catalog_resources.assert_awaited_once_with(
        "image",
        row.provider_connection_id,
        offset=0,
        limit=50,
        name=None,
        status=None,
        visibility=None,
        sort="name",
        order="asc",
        member_scope=True,
    )
    assert response.data is not None
    item = response.data.items[0]
    assert item.provider_resource_id == "image-1"
    assert not hasattr(item, "provider_attributes")


@pytest.mark.asyncio
async def test_member_catalog_detail_uses_curated_repository_lookup() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=uuid.uuid4(),
        provider_resource_id="flavor-1",
        name="medium",
        provider_status="active",
        vcpus=4,
        ram_mib=8192,
        root_disk_gib=80,
        ephemeral_disk_gib=20,
        swap_mib=1024,
        is_public=True,
        enabled=True,
        provider_attributes={"catalog_approved": True, "extra_specs": {"hw:cpu_policy": "shared"}},
    )
    inventory = SimpleNamespace(get_catalog_resource=AsyncMock(return_value=row))

    response = await get_member_catalog(
        connection_id=row.provider_connection_id,
        resource_type=CatalogMemberResourceType.FLAVOR,
        resource_id=row.id,
        uow=SimpleNamespace(inventory=inventory),
    )

    inventory.get_catalog_resource.assert_awaited_once_with(
        "flavor", row.provider_connection_id, row.id, member_scope=True
    )
    assert response.data is not None
    assert response.data.provider_resource_id == "flavor-1"
    assert not hasattr(response.data, "provider_attributes")


@pytest.mark.asyncio
async def test_member_generic_inventory_cannot_bypass_curated_image_policy() -> None:
    with pytest.raises(ResourceNotFoundError):
        await list_inventory(
            resource_type="image",
            pagination=SimpleNamespace(offset=0, limit=50, page=1),
            uow=SimpleNamespace(inventory=SimpleNamespace()),
        )


@pytest.mark.asyncio
async def test_member_catalog_passes_horizon_filters_and_deterministic_sort() -> None:
    connection_id = uuid.uuid4()
    inventory = SimpleNamespace(list_catalog_resources=AsyncMock(return_value=([], 0)))

    await list_member_catalog(
        connection_id=connection_id,
        resource_type=CatalogMemberResourceType.IMAGE,
        pagination=SimpleNamespace(offset=0, limit=25, page=1),
        name="ubuntu",
        status="active",
        visibility="public",
        sort="updated_at",
        order="desc",
        uow=SimpleNamespace(inventory=inventory),
    )

    inventory.list_catalog_resources.assert_awaited_once_with(
        "image",
        connection_id,
        offset=0,
        limit=25,
        name="ubuntu",
        status="active",
        visibility="public",
        sort="updated_at",
        order="desc",
        member_scope=True,
    )


@pytest.mark.asyncio
async def test_member_catalog_projection_exposes_safe_presentation_metadata_and_actions() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=uuid.uuid4(),
        provider_resource_id="image-1",
        name="ubuntu",
        provider_status="active",
        visibility="public",
        size_bytes=1,
        min_disk_gib=1,
        min_ram_mib=1,
        disk_format="qcow2",
        checksum="a" * 32,
        provider_attributes={
            "catalog_approved": True,
            "is_protected": False,
            "tags": ["ubuntu", "stable"],
            "properties": {"os_distro": "ubuntu"},
        },
    )

    response = await list_member_catalog(
        connection_id=row.provider_connection_id,
        resource_type=CatalogMemberResourceType.IMAGE,
        pagination=SimpleNamespace(offset=0, limit=50, page=1),
        uow=SimpleNamespace(
            inventory=SimpleNamespace(list_catalog_resources=AsyncMock(return_value=([row], 1)))
        ),
    )

    item = response.data.items[0]
    assert item.tags == ["ubuntu", "stable"]
    assert item.properties == {"os_distro": "ubuntu"}
    assert item.allowed_actions == ["deactivate", "delete"]
    assert item.capabilities == {"deactivate": True, "reactivate": False, "delete": True}
    assert not hasattr(item, "provider_attributes")


@pytest.mark.asyncio
async def test_member_catalog_drops_nested_secret_metadata_and_unknown_actions() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=uuid.uuid4(),
        provider_resource_id="image-queued",
        name="queued",
        provider_status="QUEUED",
        visibility="public",
        size_bytes=1,
        min_disk_gib=1,
        min_ram_mib=1,
        disk_format="qcow2",
        checksum="a" * 32,
        provider_attributes={
            "catalog_approved": True,
            "is_protected": None,
            "properties": {
                "safe": "yes",
                "nested": {"token": "drop", "user_data": "drop"},
            },
        },
    )
    response = await list_member_catalog(
        connection_id=row.provider_connection_id,
        resource_type=CatalogMemberResourceType.IMAGE,
        pagination=SimpleNamespace(offset=0, limit=50, page=1),
        uow=SimpleNamespace(
            inventory=SimpleNamespace(list_catalog_resources=AsyncMock(return_value=([row], 1)))
        ),
    )
    item = response.data.items[0]
    assert item.properties == {"safe": "yes", "nested": {}}
    assert item.allowed_actions == []
    assert item.capabilities == {"deactivate": False, "reactivate": False, "delete": False}
