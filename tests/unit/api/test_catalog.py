"""Catalog list/detail/compatibility API matrix tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cps.api.routers.catalog import (
    admin_router,
    check_catalog_compatibility,
    get_admin_catalog_resource,
    get_member_catalog_resource,
    list_admin_catalog,
    list_member_catalog,
    member_router,
)
from cps.api.schemas.catalog import (
    CatalogCompatibilityRequest,
    CatalogResourceType,
    CatalogStoryResourceType,
)
from cps.contracts.errors import InvalidRequestError, ResourceNotFoundError
from cps.infrastructure.db.models.enums import ConnectionScopeKind
from cps.observability.middleware import CorrelationIdMiddleware
from cps.security.auth.middleware import KeycloakAuthMiddleware
from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

CONNECTION_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
OTHER_CONNECTION_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")
PROJECT_ID = "project-1"
IMAGE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _pagination(*, offset: int = 0, limit: int = 50, page: int = 1) -> SimpleNamespace:
    return SimpleNamespace(offset=offset, limit=limit, page=page)


def _inventory(**methods: object) -> SimpleNamespace:
    defaults: dict[str, AsyncMock] = {
        "list_catalog_resources": AsyncMock(return_value=([], 0)),
        "get_catalog_resource": AsyncMock(return_value=None),
        "get_catalog_resource_by_provider_id": AsyncMock(return_value=None),
    }
    for key, value in methods.items():
        if isinstance(value, AsyncMock):
            defaults[key] = value
        else:
            defaults[key] = AsyncMock(return_value=value)
    return SimpleNamespace(**defaults)


def _project_connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=CONNECTION_ID,
        provider_id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
        scope_kind=ConnectionScopeKind.PROJECT,
        scope_project_provider_resource_id=PROJECT_ID,
    )


def _member_uow(inventory: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        inventory=inventory,
        providers=SimpleNamespace(get_connection=AsyncMock(return_value=_project_connection())),
        bindings=SimpleNamespace(get_project=AsyncMock(return_value=None)),
    )


def _image_row(**overrides: object) -> SimpleNamespace:
    base = {
        "id": IMAGE_ID,
        "provider_connection_id": CONNECTION_ID,
        "provider_resource_id": "img-1",
        "name": "ubuntu",
        "provider_status": "active",
        "lifecycle_state": "ACTIVE",
        "project_provider_resource_id": PROJECT_ID,
        "visibility": "public",
        "size_bytes": 1_073_741_824,
        "min_disk_gib": 20,
        "min_ram_mib": 512,
        "disk_format": "qcow2",
        "checksum": "abc",
        "provider_created_at": NOW,
        "provider_updated_at": NOW,
        "updated_at": NOW,
        "provider_attributes": {
            "catalog_approved": True,
            "container_format": "bare",
            "tags": ["stable"],
            "properties": {"os": "linux"},
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _flavor_row(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.UUID("22222222-2222-4222-8222-222222222222"),
        "provider_connection_id": CONNECTION_ID,
        "provider_resource_id": "flv-1",
        "name": "m1.small",
        "provider_status": "active",
        "lifecycle_state": "ACTIVE",
        "vcpus": 1,
        "ram_mib": 2048,
        "root_disk_gib": 40,
        "ephemeral_disk_gib": 0,
        "swap_mib": 0,
        "is_public": True,
        "enabled": True,
        "provider_created_at": NOW,
        "provider_updated_at": NOW,
        "updated_at": NOW,
        "provider_attributes": {"catalog_approved": True, "extra_specs": {"hw": "shared"}},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "resource_type,extra_kwargs,expected_keys",
    [
        (
            CatalogResourceType.IMAGE,
            {
                "visibility": "public",
                "owner_project_id": PROJECT_ID,
                "disk_format": "qcow2",
                "size_min_bytes": 1_000,
                "size_max_bytes": 2_000_000_000,
                "min_disk_gib": 10,
                "min_ram_mib": 256,
                "status": "active",
                "name": "ubu",
                "sort": "updated_at",
                "order": "desc",
            },
            {
                "visibility",
                "owner_project_id",
                "disk_format",
                "size_min_bytes",
                "size_max_bytes",
                "min_disk_gib",
                "min_ram_mib",
                "status",
                "name",
                "sort",
                "order",
            },
        ),
        (
            CatalogResourceType.FLAVOR,
            {
                "is_public": True,
                "min_root_disk_gib": 20,
                "min_ram_mib": 1024,
                "project_access_id": PROJECT_ID,
                "status": "active",
                "name": "m1",
            },
            {
                "is_public",
                "min_root_disk_gib",
                "min_ram_mib",
                "project_access_id",
                "status",
                "name",
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_admin_catalog_forwards_resource_specific_filters(
    resource_type: CatalogResourceType,
    extra_kwargs: dict[str, object],
    expected_keys: set[str],
) -> None:
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([], 0)))

    await list_admin_catalog(
        connection_id=CONNECTION_ID,
        resource_type=resource_type,
        pagination=_pagination(offset=25, limit=25, page=2),
        approved=False,
        include_deleted=True,
        uow=SimpleNamespace(inventory=inventory),
        **extra_kwargs,
    )

    kwargs = inventory.list_catalog_resources.await_args.kwargs
    assert inventory.list_catalog_resources.await_args.args[:2] == (
        resource_type.value,
        CONNECTION_ID,
    )
    for key in expected_keys:
        assert kwargs[key] == extra_kwargs[key]
    assert kwargs["offset"] == 25
    assert kwargs["limit"] == 25
    assert kwargs["approved"] is False
    assert kwargs["include_deleted"] is True


@pytest.mark.asyncio
async def test_admin_catalog_rejects_secret_bearing_owner_project_id() -> None:
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([], 0)))

    with pytest.raises(InvalidRequestError, match="forbidden"):
        await list_admin_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogResourceType.IMAGE,
            pagination=_pagination(offset=0, limit=25, page=1),
            approved=None,
            include_deleted=False,
            owner_project_id="https://example.com?token=secret",
            uow=SimpleNamespace(inventory=inventory),
        )

    inventory.list_catalog_resources.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_catalog_rejects_secret_bearing_project_access_id() -> None:
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([], 0)))

    with pytest.raises(InvalidRequestError, match="forbidden"):
        await list_admin_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogResourceType.FLAVOR,
            pagination=_pagination(offset=0, limit=25, page=1),
            approved=None,
            include_deleted=False,
            project_access_id="password=project-scope",
            uow=SimpleNamespace(inventory=inventory),
        )

    inventory.list_catalog_resources.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_catalog_forwards_common_filters_and_forces_member_policy() -> None:
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([_image_row()], 1)))

    await list_member_catalog(
        connection_id=CONNECTION_ID,
        resource_type=CatalogStoryResourceType.IMAGE,
        pagination=_pagination(offset=100, limit=10),
        name="ubuntu",
        status="active",
        visibility="public",
        sort="name",
        order="asc",
        uow=_member_uow(inventory),
    )

    kwargs = inventory.list_catalog_resources.await_args.kwargs
    assert kwargs["approved"] is True
    assert kwargs["include_deleted"] is False
    assert kwargs["member_public_catalog_only"] is True
    assert "member_project_scope" not in kwargs
    assert "owner_project_id" not in kwargs
    assert "project_access_id" not in kwargs
    assert kwargs["offset"] == 100
    assert kwargs["limit"] == 10
    assert kwargs["name"] == "ubuntu"
    assert kwargs["visibility"] == "public"


@pytest.mark.asyncio
async def test_resolve_pagination_maps_page_to_offset() -> None:
    from cps.api.pagination import resolve_pagination

    params = resolve_pagination(offset=None, page=3, limit=20)
    assert params.offset == 40
    assert params.page == 3
    assert params.limit == 20


@pytest.mark.parametrize(
    "approved,include_deleted",
    [(True, None), (False, None), (None, True), (None, False)],
)
@pytest.mark.asyncio
async def test_member_catalog_rejects_admin_only_filters(
    approved: bool | None,
    include_deleted: bool | None,
) -> None:
    with pytest.raises(InvalidRequestError):
        await list_member_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            pagination=_pagination(),
            approved=approved,
            include_deleted=include_deleted,
            uow=_member_uow(_inventory()),
        )


@pytest.mark.parametrize(
    "resource_type,forbidden_kwargs",
    [
        ("flavor", {"visibility": "public"}),
        ("flavor", {"disk_format": "qcow2"}),
        ("flavor", {"owner_project_id": PROJECT_ID}),
        ("image", {"project_access_id": PROJECT_ID}),
        ("image", {"owner_project_id": PROJECT_ID}),
        ("image", {"min_root_disk_gib": 10}),
    ],
)
@pytest.mark.asyncio
async def test_catalog_rejects_wrong_resource_type_filters(
    resource_type: str,
    forbidden_kwargs: dict[str, object],
) -> None:
    with pytest.raises(InvalidRequestError):
        await list_member_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType(resource_type),
            pagination=_pagination(),
            uow=_member_uow(_inventory()),
            **forbidden_kwargs,
        )


@pytest.mark.asyncio
async def test_catalog_rejects_inverted_size_range() -> None:
    with pytest.raises(InvalidRequestError):
        await list_admin_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogResourceType.IMAGE,
            pagination=_pagination(),
            size_min_bytes=2_000,
            size_max_bytes=1_000,
            uow=SimpleNamespace(inventory=_inventory()),
        )


@pytest.mark.asyncio
async def test_member_catalog_applies_scope_in_repository_before_pagination() -> None:
    inventory = _inventory(
        list_catalog_resources=AsyncMock(
            return_value=([_image_row(name="visible")], 1),
        )
    )

    response = await list_member_catalog(
        connection_id=CONNECTION_ID,
        resource_type=CatalogStoryResourceType.IMAGE,
        pagination=_pagination(),
        uow=_member_uow(inventory),
    )

    kwargs = inventory.list_catalog_resources.await_args.kwargs
    assert kwargs["member_public_catalog_only"] is True
    assert "member_project_scope" not in kwargs
    assert len(response.data.items) == 1
    assert response.data.total == 1


@pytest.mark.asyncio
async def test_member_catalog_detail_success_has_bounded_fields_only() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "container_format": "bare",
                    "tags": ["stable"],
                    "properties": {"os": "linux"},
                    "member_project_ids": ["project-2"],
                    "is_protected": True,
                }
            )
        )
    )

    response = await get_member_catalog_resource(
        connection_id=CONNECTION_ID,
        resource_type=CatalogStoryResourceType.IMAGE,
        resource_id=IMAGE_ID,
        uow=_member_uow(inventory),
    )

    payload = response.data.model_dump()
    assert "provider_attributes" not in payload
    assert payload["catalog_approved"] is True
    assert payload["disk_format"] == "qcow2"
    for forbidden in (
        "properties",
        "member_project_ids",
        "tags",
        "is_protected",
        "container_format",
        "virtual_size_bytes",
        "extra_specs",
        "access_project_ids",
    ):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_non_object_provider_attributes() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(provider_attributes=["not", "a", "dict"])
        )
    )

    with pytest.raises(InvalidRequestError, match="invalid"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_bool_virtual_size_bytes() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "virtual_size_bytes": True,
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="virtual_size_bytes"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_overlong_container_format() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "container_format": "x" * 256,
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="container_format"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_overlong_name() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(return_value=_image_row(name="x" * 256))
    )

    with pytest.raises(InvalidRequestError, match="name"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_secret_bearing_checksum() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(checksum="https://example.com?token=abc")
        )
    )

    with pytest.raises(InvalidRequestError, match="forbidden"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_secret_bearing_container_format() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "container_format": "https://storage.example/x?X-Goog-Signature=abc",
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="forbidden"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_compatibility_masks_invalid_provider_attributes_as_not_found() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[
                _image_row(provider_attributes="not-a-dict"),
                _flavor_row(
                    provider_attributes={
                        "catalog_approved": True,
                        "access_project_ids": [123],
                    }
                ),
            ],
        ),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(body=body, uow=_member_uow(inventory))

    assert response.data.compatible is False
    assert response.data.reason_codes == ["IMAGE_NOT_FOUND", "FLAVOR_NOT_FOUND"]


@pytest.mark.asyncio
async def test_compatibility_masks_secret_bearing_container_format_as_not_found() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[
                _image_row(
                    provider_attributes={
                        "catalog_approved": True,
                        "container_format": "https://example.com?token=abc",
                    }
                ),
                _flavor_row(),
            ],
        ),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(body=body, uow=_member_uow(inventory))

    assert response.data.compatible is False
    assert response.data.reason_codes == ["IMAGE_NOT_FOUND"]


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_invalid_legacy_metadata() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "tags": [123, "ok"],
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="invalid"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_out_of_range_flavor_dimensions() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(return_value=_flavor_row(vcpus=-1))
    )

    with pytest.raises(InvalidRequestError, match="out of range"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.FLAVOR,
            resource_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_bool_is_protected() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={"catalog_approved": True, "is_protected": 1}
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="is_protected"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_compatibility_masks_negative_flavor_dimensions_as_not_found() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[_image_row(), _flavor_row(ram_mib=-1)],
        )
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(body=body, uow=_member_uow(inventory))

    assert response.data.compatible is False
    assert response.data.reason_codes == ["FLAVOR_NOT_FOUND"]


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_overlong_legacy_list_entries() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "tags": ["x" * 256],
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="maximum length"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_rejects_oversized_legacy_projection() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "properties": {"pad": "z" * 129},
                }
            )
        )
    )

    with pytest.raises(InvalidRequestError, match="exceed"):
        await get_admin_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.parametrize(
    "row_factory",
    [
        lambda: None,
        lambda: _image_row(provider_status="deactivated"),
        lambda: _image_row(lifecycle_state="DELETED"),
        lambda: _image_row(visibility="private", project_provider_resource_id="other"),
    ],
)
@pytest.mark.asyncio
async def test_member_catalog_detail_is_404_for_missing_stale_or_out_of_scope(
    row_factory,
) -> None:
    inventory = _inventory(get_catalog_resource=AsyncMock(return_value=row_factory()))

    with pytest.raises(ResourceNotFoundError):
        await get_member_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=_member_uow(inventory),
        )


@pytest.mark.asyncio
async def test_admin_catalog_detail_can_return_unapproved_and_deleted() -> None:
    deleted = _image_row(
        lifecycle_state="DELETED",
        provider_attributes={"catalog_approved": False},
    )
    inventory = _inventory(get_catalog_resource=AsyncMock(return_value=deleted))

    response = await get_admin_catalog_resource(
        connection_id=CONNECTION_ID,
        resource_type=CatalogStoryResourceType.IMAGE,
        resource_id=IMAGE_ID,
        include_deleted=True,
        uow=SimpleNamespace(inventory=inventory),
    )

    assert response.data.lifecycle_state == "DELETED"
    assert response.data.catalog_approved is False
    assert "provider_attributes" not in response.data.model_dump()


@pytest.mark.asyncio
async def test_admin_catalog_detail_404_for_cross_connection() -> None:
    inventory = _inventory(get_catalog_resource=AsyncMock(return_value=None))

    with pytest.raises(ResourceNotFoundError):
        await get_admin_catalog_resource(
            connection_id=OTHER_CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=inventory),
        )


@pytest.mark.asyncio
async def test_compatibility_api_returns_deterministic_reason_codes() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(return_value=None),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(
        body=body,
        uow=_member_uow(inventory),
    )

    assert response.data.compatible is False
    assert response.data.reason_codes == ["IMAGE_NOT_FOUND", "FLAVOR_NOT_FOUND"]


@pytest.mark.asyncio
async def test_compatibility_api_reports_launch_incompatibilities() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[_image_row(min_ram_mib=4096), _flavor_row(ram_mib=2048)]
        ),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(
        body=body,
        uow=_member_uow(inventory),
    )

    assert response.data.compatible is False
    assert "FLAVOR_RAM_BELOW_IMAGE_MINIMUM" in response.data.reason_codes


@pytest.mark.parametrize(
    ("use", "image_factory", "flavor_factory", "expected_reason"),
    [
        (
            "LAUNCH",
            lambda: _image_row(provider_connection_id=OTHER_CONNECTION_ID),
            lambda: _flavor_row(),
            "IMAGE_NOT_FOUND",
        ),
        (
            "LAUNCH",
            lambda: _image_row(provider_attributes={"catalog_approved": False}),
            lambda: _flavor_row(),
            "IMAGE_NOT_FOUND",
        ),
        (
            "LAUNCH",
            lambda: _image_row(provider_status="deactivated"),
            lambda: _flavor_row(),
            "IMAGE_NOT_FOUND",
        ),
        (
            "LAUNCH",
            lambda: _image_row(disk_format="aki"),
            lambda: _flavor_row(),
            "IMAGE_FORMAT_NOT_LAUNCHABLE",
        ),
        (
            "LAUNCH",
            lambda: _image_row(min_disk_gib=80),
            lambda: _flavor_row(root_disk_gib=40),
            "FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM",
        ),
        (
            "LAUNCH",
            lambda: _image_row(),
            lambda: _flavor_row(provider_attributes={"catalog_approved": False}),
            "FLAVOR_NOT_FOUND",
        ),
        (
            "LAUNCH",
            lambda: _image_row(),
            lambda: _flavor_row(is_public=False, provider_attributes={"catalog_approved": True}),
            "FLAVOR_NOT_FOUND",
        ),
        (
            "VOLUME_FROM_IMAGE",
            lambda: _image_row(min_disk_gib=None),
            lambda: None,
            "CATALOG_DATA_INCOMPLETE",
        ),
    ],
)
@pytest.mark.asyncio
async def test_compatibility_api_reports_specific_reason_codes(
    use: str,
    image_factory,
    flavor_factory,
    expected_reason: str,
) -> None:
    image_row = image_factory()
    flavor_row = flavor_factory() if flavor_factory is not None else None
    side_effect = [image_row]
    if flavor_row is not None:
        side_effect.append(flavor_row)
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(side_effect=side_effect),
    )
    body = CatalogCompatibilityRequest(
        use=use,  # type: ignore[arg-type]
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1" if flavor_row is not None else None,
    )

    response = await check_catalog_compatibility(
        body=body,
        uow=_member_uow(inventory),
    )

    assert response.data.compatible is False
    assert expected_reason in response.data.reason_codes


@pytest.mark.parametrize(
    "row_factory",
    [
        lambda: _image_row(provider_attributes={"catalog_approved": False}),
        lambda: _image_row(provider_status="deactivated"),
        lambda: _image_row(visibility="private"),
        lambda: _image_row(visibility="shared"),
    ],
)
@pytest.mark.asyncio
async def test_member_compatibility_masks_inaccessible_image_as_not_found(row_factory) -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[row_factory(), _flavor_row()],
        ),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(body=body, uow=_member_uow(inventory))

    assert response.data.compatible is False
    assert response.data.reason_codes == ["IMAGE_NOT_FOUND"]


@pytest.mark.asyncio
async def test_member_compatibility_masks_private_flavor_as_not_found() -> None:
    inventory = _inventory(
        get_catalog_resource_by_provider_id=AsyncMock(
            side_effect=[_image_row(), _flavor_row(is_public=False)],
        ),
    )
    body = CatalogCompatibilityRequest(
        use="LAUNCH",
        provider_connection_id=CONNECTION_ID,
        image_provider_resource_id="img-1",
        flavor_provider_resource_id="flv-1",
    )

    response = await check_catalog_compatibility(body=body, uow=_member_uow(inventory))

    assert response.data.compatible is False
    assert response.data.reason_codes == ["FLAVOR_NOT_FOUND"]


def test_admin_catalog_resource_type_enum_includes_cps_1703_curated_types() -> None:
    assert {item.value for item in CatalogResourceType} == {
        "image",
        "flavor",
        "network",
        "volume-type",
        "availability-zone",
    }
    assert {item.value for item in CatalogStoryResourceType} == {"image", "flavor"}


@pytest.mark.parametrize(
    "resource_type",
    [
        CatalogResourceType.NETWORK,
        CatalogResourceType.VOLUME_TYPE,
        CatalogResourceType.AVAILABILITY_ZONE,
    ],
)
@pytest.mark.asyncio
async def test_admin_catalog_lists_cps_1703_curated_resource_types(
    resource_type: CatalogResourceType,
) -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=CONNECTION_ID,
        provider_resource_id="curated-1",
        name="curated",
        description=None,
        provider_status="active",
        lifecycle_state="ACTIVE",
        provider_created_at=NOW,
        provider_updated_at=NOW,
        last_seen_at=NOW,
        deleted_at=None,
        last_sync_id=None,
        provider_attributes={"catalog_approved": True},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([row], 1)))

    response = await list_admin_catalog(
        connection_id=CONNECTION_ID,
        resource_type=resource_type,
        pagination=_pagination(),
        uow=SimpleNamespace(inventory=inventory),
    )

    assert response.data.total == 1
    item = response.data.items[0]
    assert item.provider_resource_id == "curated-1"
    assert item.catalog_approved is True
    dumped = item.model_dump()
    assert "provider_attributes" not in dumped
    assert dumped["catalog_approved"] is True
    inventory.list_catalog_resources.assert_awaited_once()
    assert inventory.list_catalog_resources.await_args.kwargs.get("visibility") is None


@pytest.mark.parametrize(
    "provider_attributes",
    [
        {"catalog_approved": False},
        {"catalog_approved": "true"},
        {"catalog_approved": 1},
        {},
    ],
)
@pytest.mark.asyncio
async def test_admin_catalog_curated_view_catalog_approved_is_false_for_non_canonical_marker(
    provider_attributes: dict[str, object],
) -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=CONNECTION_ID,
        provider_resource_id="curated-unapproved",
        name="curated",
        description=None,
        provider_status="active",
        lifecycle_state="ACTIVE",
        provider_created_at=NOW,
        provider_updated_at=NOW,
        last_seen_at=NOW,
        deleted_at=None,
        last_sync_id=None,
        provider_attributes=provider_attributes,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([row], 1)))

    response = await list_admin_catalog(
        connection_id=CONNECTION_ID,
        resource_type=CatalogResourceType.NETWORK,
        pagination=_pagination(),
        uow=SimpleNamespace(inventory=inventory),
    )

    assert response.data.items[0].catalog_approved is False
    assert "provider_attributes" not in response.data.items[0].model_dump()


@pytest.mark.asyncio
async def test_admin_catalog_curated_approved_filter_matches_catalog_approved_field() -> None:
    approved_row = SimpleNamespace(
        id=uuid.uuid4(),
        provider_connection_id=CONNECTION_ID,
        provider_resource_id="approved-net",
        name="approved",
        description=None,
        provider_status="active",
        lifecycle_state="ACTIVE",
        provider_created_at=NOW,
        provider_updated_at=NOW,
        last_seen_at=NOW,
        deleted_at=None,
        last_sync_id=None,
        provider_attributes={"catalog_approved": True},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    inventory = _inventory(list_catalog_resources=AsyncMock(return_value=([approved_row], 1)))

    response = await list_admin_catalog(
        connection_id=CONNECTION_ID,
        resource_type=CatalogResourceType.NETWORK,
        pagination=_pagination(),
        approved=True,
        uow=SimpleNamespace(inventory=inventory),
    )

    assert response.data.total == 1
    assert response.data.items[0].catalog_approved is True
    assert inventory.list_catalog_resources.await_args.kwargs["approved"] is True


@pytest.mark.asyncio
async def test_admin_catalog_rejects_image_filters_for_network_resource_type() -> None:
    with pytest.raises(InvalidRequestError, match="not valid"):
        await list_admin_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogResourceType.NETWORK,
            pagination=_pagination(),
            visibility="public",
            uow=SimpleNamespace(inventory=_inventory()),
        )


async def _verify_side_effect(token: str) -> AuthenticatedPrincipal:
    if token == "admin-token":
        return AuthenticatedPrincipal(
            subject="admin-user",
            roles=frozenset({"admin"}),
            client_id="cmp",
        )
    if token == "member-token":
        return AuthenticatedPrincipal(
            subject="member-user",
            roles=frozenset({"member"}),
            client_id="cmp",
        )
    raise JwtVerificationError("invalid token")


def _catalog_auth_app() -> TestClient:
    inventory = _inventory()
    app = FastAPI()
    app.include_router(member_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1/admin")

    async def _uow_override() -> SimpleNamespace:
        yield _member_uow(inventory)

    from cps.api.dependencies import get_uow

    app.dependency_overrides[get_uow] = _uow_override

    verifier = KeycloakJwtVerifier.from_settings(
        issuer="http://127.0.0.1:8080/realms/vnpost",
        client_id="cmp",
        audience=None,
        jwks_cache_ttl_seconds=300,
    )
    verifier.verify = AsyncMock(side_effect=_verify_side_effect)  # type: ignore[method-assign]
    app.add_middleware(KeycloakAuthMiddleware, verifier=verifier)
    app.add_middleware(CorrelationIdMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_admin_catalog_detail_http_returns_422_for_legacy_non_object_metadata() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(
                provider_attributes={
                    "catalog_approved": True,
                    "properties": "not-an-object",
                }
            )
        )
    )
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    from cps.api.dependencies import get_uow
    from cps.api.errors import register_error_handlers

    async def _uow_override() -> SimpleNamespace:
        yield SimpleNamespace(
            inventory=inventory,
            providers=SimpleNamespace(get_connection=AsyncMock(return_value=_project_connection())),
            bindings=SimpleNamespace(get_project=AsyncMock(return_value=None)),
        )

    app.dependency_overrides[get_uow] = _uow_override
    register_error_handlers(app)
    verifier = KeycloakJwtVerifier.from_settings(
        issuer="http://127.0.0.1:8080/realms/vnpost",
        client_id="cmp",
        audience=None,
        jwks_cache_ttl_seconds=300,
    )
    verifier.verify = AsyncMock(
        return_value=AuthenticatedPrincipal(
            subject="admin-user",
            roles=frozenset({"admin"}),
            client_id="cmp",
        )
    )
    app.add_middleware(KeycloakAuthMiddleware, verifier=verifier)
    app.add_middleware(CorrelationIdMiddleware)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        f"/api/v1/admin/provider-connections/{CONNECTION_ID}/catalog/image/{IMAGE_ID}",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert response.status_code == 400
    assert response.json()["errorCode"] == "VALIDATION_FAILED"


def test_catalog_routes_enforce_member_and_admin_dependencies() -> None:
    client = _catalog_auth_app()
    member_headers = {"Authorization": "Bearer member-token"}
    admin_headers = {"Authorization": "Bearer admin-token"}
    member_list = f"/api/v1/provider-connections/{CONNECTION_ID}/catalog?resource_type=image"
    admin_list = f"/api/v1/admin/provider-connections/{CONNECTION_ID}/catalog?resource_type=image"

    assert client.get(member_list, headers=admin_headers).status_code == 403
    assert client.get(admin_list, headers=member_headers).status_code == 403
    assert client.get(member_list).status_code == 401
    assert client.get(admin_list).status_code == 401
    assert client.get(member_list, headers=member_headers).status_code == 200
    assert client.get(admin_list, headers=admin_headers).status_code == 200


@pytest.mark.parametrize("resource_type", ["image", "flavor", "images", "flavors"])
@pytest.mark.asyncio
async def test_generic_inventory_routes_reject_catalog_resource_types(resource_type: str) -> None:
    from cps.api.routers.inventory import get_inventory, list_inventory

    with pytest.raises(ResourceNotFoundError):
        await list_inventory(
            resource_type=resource_type,
            pagination=_pagination(),
            uow=SimpleNamespace(inventory=_inventory()),
        )
    with pytest.raises(ResourceNotFoundError):
        await get_inventory(
            resource_type=resource_type,
            resource_id=IMAGE_ID,
            uow=SimpleNamespace(inventory=_inventory()),
        )


@pytest.mark.asyncio
async def test_member_catalog_detail_returns_404_for_malformed_legacy_projection() -> None:
    inventory = _inventory(
        get_catalog_resource=AsyncMock(
            return_value=_image_row(disk_format="not-valid"),
        )
    )

    with pytest.raises(ResourceNotFoundError):
        await get_member_catalog_resource(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            resource_id=IMAGE_ID,
            uow=_member_uow(inventory),
        )


@pytest.mark.asyncio
async def test_member_catalog_list_returns_404_for_malformed_legacy_projection() -> None:
    inventory = _inventory(
        list_catalog_resources=AsyncMock(
            return_value=([_image_row(disk_format="not-valid")], 1),
        )
    )

    with pytest.raises(ResourceNotFoundError):
        await list_member_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogStoryResourceType.IMAGE,
            pagination=_pagination(),
            uow=_member_uow(inventory),
        )


@pytest.mark.asyncio
async def test_compatibility_request_rejects_unknown_scope_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CatalogCompatibilityRequest.model_validate(
            {
                "use": "LAUNCH",
                "provider_connection_id": str(CONNECTION_ID),
                "project_provider_resource_id": PROJECT_ID,
                "image_provider_resource_id": "img-1",
                "flavor_provider_resource_id": "flv-1",
            }
        )


@pytest.mark.asyncio
async def test_catalog_rejects_numeric_filter_above_contract_maximum() -> None:
    with pytest.raises(InvalidRequestError, match="size_min_bytes"):
        await list_admin_catalog(
            connection_id=CONNECTION_ID,
            resource_type=CatalogResourceType.IMAGE,
            pagination=_pagination(),
            size_min_bytes=9_223_372_036_854_775_808,
            uow=SimpleNamespace(inventory=_inventory()),
        )
