"""Read-only administrator-curated provider catalog."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.api.schemas.catalog import CatalogPage, CatalogResourceType
from cps.api.schemas.inventory import InventoryResourceView
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin

router = APIRouter(tags=["Admin Catalog"], dependencies=[Depends(require_admin)])


@router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=CatalogPage,
)
async def list_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogResourceType,
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CatalogPage:
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=offset,
            limit=limit,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return CatalogPage(
        items=[InventoryResourceView.model_validate(row, from_attributes=True) for row in rows],
        page={"offset": offset, "limit": limit, "total": total},
    )
