"""Public provider CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from cps.api.dependencies import get_uow
from cps.api.schemas.providers import ProviderCreate, ProviderPage, ProviderPatch, ProviderView
from cps.application.providers import ProviderService
from cps.infrastructure.db.models.enums import ProviderStatus
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


@router.post("", response_model=ProviderView, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ProviderView:
    result = await ProviderService(uow.providers).create(body)
    await uow.commit()
    return result


@router.get("", response_model=ProviderPage)
async def list_providers(
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    status_filter: ProviderStatus | None = Query(default=None, alias="status"),  # noqa: B008
    name: str | None = Query(default=None, max_length=255),  # noqa: B008
    provider_type: str | None = Query(default=None, pattern="^OPENSTACK$"),  # noqa: B008
    sort: str = Query(default="name", pattern="^(name|created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ProviderPage:
    return await ProviderService(uow.providers).list(
        offset=offset,
        limit=min(limit, 200),
        status=status_filter,
        name=name,
        provider_type=provider_type,
        sort=sort,
        order=order,
    )


@router.get("/{provider_id}", response_model=ProviderView)
async def get_provider(
    provider_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ProviderView:
    return await ProviderService(uow.providers).get(provider_id)


@router.patch("/{provider_id}", response_model=ProviderView)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderPatch,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ProviderView:
    result = await ProviderService(uow.providers).update(provider_id, body.expected_version, body)
    await uow.commit()
    return result
