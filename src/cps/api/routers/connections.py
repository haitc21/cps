"""Provider connection admin and member capability endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from cps.api.dependencies import get_uow
from cps.api.schemas.connections import (
    ConnectionCreate,
    ConnectionPage,
    ConnectionPatch,
    ConnectionView,
)
from cps.application.connections import ConnectionService
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
    response_model=ConnectionView,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    provider_id: uuid.UUID,
    body: ConnectionCreate,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ConnectionView:
    result = await _service(uow).create(provider_id, body)
    await uow.commit()
    return result


@admin_router.get("/provider-connections/{connection_id}", response_model=ConnectionView)
async def get_connection(
    connection_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ConnectionView:
    return await _service(uow).get(connection_id)


@admin_router.get("/provider-connections", response_model=ConnectionPage)
async def list_connections(
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    provider_id: uuid.UUID | None = None,
    status_filter: ConnectionStatus | None = Query(default=None, alias="status"),  # noqa: B008
    sort: str = Query(default="created_at", pattern="^(created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ConnectionPage:
    return await _service(uow).list(
        offset=offset,
        limit=limit,
        provider_id=provider_id,
        status=status_filter,
        sort=sort,
        order=order,
    )


@member_router.get("/provider-connections/{connection_id}/capabilities")
async def get_capabilities(
    connection_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> dict[str, object]:
    connection = await _service(uow).get(connection_id)
    if connection.capabilities is None:
        from cps.contracts.errors import CapabilitiesNotAvailableError

        raise CapabilitiesNotAvailableError
    return connection.capabilities


@admin_router.patch("/provider-connections/{connection_id}", response_model=ConnectionView)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ConnectionView:
    result = await _service(uow).update(connection_id, body)
    await uow.commit()
    return result
