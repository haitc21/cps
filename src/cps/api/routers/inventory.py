"""Inventory list/get APIs with uniform safe pagination."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.api.schemas.inventory import InventoryPage, InventoryResourceView
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(tags=["inventory"])


def _view(row: object) -> InventoryResourceView:
    return InventoryResourceView.model_validate(row, from_attributes=True)


@router.get("/api/v1/{resource_type}", response_model=InventoryPage)
async def list_inventory(
    resource_type: str,
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    provider_connection_id: uuid.UUID | None = None,
    provider_resource_id: str | None = None,
    name: str | None = Query(default=None, max_length=255),  # noqa: B008
    include_deleted: bool = False,
    sort: str = Query(default="created_at", pattern="^(name|created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> InventoryPage:
    try:
        rows, total = await uow.inventory.list_resources(
            resource_type,
            offset=offset,
            limit=limit,
            provider_connection_id=provider_connection_id,
            provider_resource_id=provider_resource_id,
            name=name,
            include_deleted=include_deleted,
            sort=sort,
            order=order,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return InventoryPage(
        items=[_view(row) for row in rows],
        page={"offset": offset, "limit": limit, "total": total},
    )


@router.get("/api/v1/{resource_type}/{resource_id}", response_model=InventoryResourceView)
async def get_inventory(
    resource_type: str,
    resource_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> InventoryResourceView:
    try:
        row = await uow.inventory.get_resource(resource_type, resource_id)
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    return _view(row)
