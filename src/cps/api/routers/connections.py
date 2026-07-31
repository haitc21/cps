"""Provider connection admin and member capability endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.connections import (
    ConnectionCreate,
    ConnectionPatch,
    ConnectionView,
)
from cps.application.connections import ConnectionService
from cps.contracts.api_response import BaseResponse, PagedData
from cps.infrastructure.db.models.enums import ConnectionStatus
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin, require_member

admin_router = APIRouter(
    tags=["Admin Provider Connections"],
    dependencies=[Depends(require_admin)],
)
member_router = APIRouter(
    tags=["Provider Connections"],
    dependencies=[Depends(require_member)],
)


def _service(uow: SqlAlchemyUnitOfWork) -> ConnectionService:
    return ConnectionService(uow.providers)


@admin_router.post(
    "/providers/{provider_id}/connections",
    response_model=BaseResponse[ConnectionView],
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    provider_id: uuid.UUID,
    body: ConnectionCreate,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ConnectionView]:
    result = await _service(uow).create(provider_id, body)
    await uow.commit()
    return api_success(result, status_code=status.HTTP_201_CREATED)


@admin_router.get(
    "/provider-connections/{connection_id}",
    response_model=BaseResponse[ConnectionView],
)
async def get_connection(
    connection_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ConnectionView]:
    return api_success(await _service(uow).get(connection_id))


@admin_router.get(
    "/provider-connections",
    response_model=BaseResponse[PagedData[ConnectionView]],
)
async def list_connections(
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    provider_id: uuid.UUID | None = None,
    status_filter: ConnectionStatus | None = Query(default=None, alias="status"),  # noqa: B008
    sort: str = Query(default="created_at", pattern="^(created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[ConnectionView]]:
    result = await _service(uow).list(
        offset=pagination.offset,
        limit=pagination.limit,
        provider_id=provider_id,
        status=status_filter,
        sort=sort,
        order=order,
    )
    return api_success(
        paged_from_offset(
            result.items,
            offset=pagination.offset,
            limit=pagination.limit,
            total=result.page.total,
        )
    )


@member_router.get(
    "/provider-connections/{connection_id}/capabilities",
    response_model=BaseResponse[dict[str, object]],
)
async def get_capabilities(
    connection_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[dict[str, object]]:
    connection = await _service(uow).get(connection_id)
    if connection.capabilities is None:
        from cps.contracts.errors import CapabilitiesNotAvailableError

        raise CapabilitiesNotAvailableError
    return api_success(connection.capabilities)


@admin_router.patch(
    "/provider-connections/{connection_id}",
    response_model=BaseResponse[ConnectionView],
)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ConnectionView]:
    result = await _service(uow).update(connection_id, body)
    await uow.commit()
    return api_success(result)
