"""Read-only administrator-curated provider catalog."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.catalog import (
    CatalogFlavorSummary,
    CatalogImageSummary,
    CatalogMemberResourceSummary,
    CatalogMemberResourceType,
    CatalogResourceType,
)
from cps.api.schemas.inventory import InventoryResourceView
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin, require_member

admin_router = APIRouter(tags=["Admin Catalog"], dependencies=[Depends(require_admin)])
member_router = APIRouter(tags=["Catalog"], dependencies=[Depends(require_member)])
# Compatibility name for callers that still import the original admin router.
router = admin_router


@admin_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[PagedData[InventoryResourceView]],
)
async def list_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogResourceType,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[InventoryResourceView]]:
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return api_success(
        paged_from_offset(
            [InventoryResourceView.model_validate(row, from_attributes=True) for row in rows],
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


def _member_view(
    resource_type: CatalogMemberResourceType, row: object
) -> CatalogMemberResourceSummary:
    values = vars(row)
    attributes = values.get("provider_attributes", {})
    approved = attributes.get("catalog_approved") is True if isinstance(attributes, dict) else False
    common = {
        "id": values.get("id"),
        "provider_connection_id": values.get("provider_connection_id"),
        "provider_resource_id": values.get("provider_resource_id"),
        "name": values.get("name"),
        "provider_status": values.get("provider_status"),
        "catalog_approved": approved,
    }
    if resource_type is CatalogMemberResourceType.IMAGE:
        return CatalogImageSummary.model_validate(
            {
                **common,
                "visibility": values.get("visibility"),
                "size_bytes": values.get("size_bytes"),
                "min_disk_gib": values.get("min_disk_gib"),
                "min_ram_mib": values.get("min_ram_mib"),
                "disk_format": values.get("disk_format"),
                "checksum": values.get("checksum"),
            }
        )
    return CatalogFlavorSummary.model_validate(
        {
            **common,
            "vcpus": values.get("vcpus"),
            "ram_mib": values.get("ram_mib"),
            "root_disk_gib": values.get("root_disk_gib"),
            "ephemeral_disk_gib": values.get("ephemeral_disk_gib"),
            "swap_mib": values.get("swap_mib"),
            "is_public": values.get("is_public"),
            "enabled": values.get("enabled"),
        }
    )


@member_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[PagedData[CatalogMemberResourceSummary]],
)
async def list_member_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogMemberResourceType,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[CatalogMemberResourceSummary]]:
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return api_success(
        paged_from_offset(
            [_member_view(resource_type, row) for row in rows],
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


@member_router.get(
    "/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
    response_model=BaseResponse[CatalogMemberResourceSummary],
)
async def get_member_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogMemberResourceType,
    resource_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[CatalogMemberResourceSummary]:
    try:
        row = await uow.inventory.get_catalog_resource(
            resource_type.value, connection_id, resource_id
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    return api_success(_member_view(resource_type, row))
