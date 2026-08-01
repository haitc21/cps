"""Inventory list/get APIs with uniform safe pagination."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.inventory import InventoryResourceView
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_member

router = APIRouter(tags=["Inventory"], dependencies=[Depends(require_member)])


def _view(row: object) -> InventoryResourceView:
    return InventoryResourceView.model_validate(row, from_attributes=True)


@router.get("/{resource_type}", response_model=BaseResponse[PagedData[InventoryResourceView]])
async def list_inventory(
    resource_type: str,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    provider_connection_id: uuid.UUID | None = None,
    provider_resource_id: str | None = None,
    project_provider_resource_id: str | None = Query(default=None, max_length=255),  # noqa: B008
    name: str | None = Query(default=None, max_length=255),  # noqa: B008
    include_deleted: bool = False,
    sort: str = Query(default="created_at", pattern="^(name|created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[InventoryResourceView]]:
    if resource_type in {"image", "flavor", "images", "flavors"}:
        raise ResourceNotFoundError
    try:
        rows, total = await uow.inventory.list_resources(
            resource_type,
            offset=pagination.offset,
            limit=pagination.limit,
            provider_connection_id=provider_connection_id,
            provider_resource_id=provider_resource_id,
            project_provider_resource_id=project_provider_resource_id,
            name=name,
            include_deleted=include_deleted,
            sort=sort,
            order=order,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return api_success(
        paged_from_offset(
            [_view(row) for row in rows],
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


@router.get("/{resource_type}/{resource_id}", response_model=BaseResponse[InventoryResourceView])
async def get_inventory(
    resource_type: str,
    resource_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[InventoryResourceView]:
    if resource_type in {"image", "flavor", "images", "flavors"}:
        raise ResourceNotFoundError
    try:
        row = await uow.inventory.get_resource(resource_type, resource_id)
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    return api_success(_view(row))
