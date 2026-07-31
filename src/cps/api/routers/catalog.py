"""Read-only administrator-curated provider catalog."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.catalog import CatalogResourceType
from cps.api.schemas.inventory import InventoryResourceView
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin

router = APIRouter(tags=["Admin Catalog"], dependencies=[Depends(require_admin)])


@router.get(
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
