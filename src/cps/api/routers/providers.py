"""Admin provider CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, status

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.prefixes import admin_operation_status_url
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.bindings import (
    IdentityBindingAccepted,
    IdentityBindingView,
    IdentityDomainBindingCreate,
    IdentityProjectBindingCreate,
)
from cps.api.schemas.providers import ProviderCreate, ProviderPatch, ProviderView
from cps.application.bindings import IdentityBindingService
from cps.application.operations import OperationApplicationService
from cps.application.providers import ProviderService
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import CredentialKeyUnavailableError
from cps.infrastructure.db.models.enums import ProviderStatus
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin

router = APIRouter(
    prefix="/providers",
    tags=["Admin Providers"],
    dependencies=[Depends(require_admin)],
)


def _service(uow: SqlAlchemyUnitOfWork) -> ProviderService:
    settings = uow.session.info["settings"]
    cipher = uow.session.info["credential_cipher"]
    return ProviderService(
        uow.providers,
        cipher=cipher,
        active_key_version=settings.credential_active_key_version,
    )


def _binding_service(uow: SqlAlchemyUnitOfWork) -> IdentityBindingService:
    return IdentityBindingService(
        uow.providers,
        uow.bindings,
        OperationApplicationService(uow.operations, uow.outbox, uow.inventory),
    )


@router.post(
    "",
    response_model=BaseResponse[ProviderView],
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    body: ProviderCreate,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ProviderView]:
    if uow.session.info["credential_cipher"] is None:
        raise CredentialKeyUnavailableError
    result = await _service(uow).create(body)
    await uow.commit()
    return api_success(result, status_code=status.HTTP_201_CREATED)


@router.get("", response_model=BaseResponse[PagedData[ProviderView]])
async def list_providers(
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    status_filter: ProviderStatus | None = Query(default=None, alias="status"),  # noqa: B008
    name: str | None = Query(default=None, max_length=255),  # noqa: B008
    provider_type: str | None = Query(default=None, pattern="^OPENSTACK$"),  # noqa: B008
    sort: str = Query(default="name", pattern="^(name|created_at|updated_at)$"),  # noqa: B008
    order: str = Query(default="asc", pattern="^(asc|desc)$"),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[ProviderView]]:
    result = await _service(uow).list(
        offset=pagination.offset,
        limit=pagination.limit,
        status=status_filter,
        name=name,
        provider_type=provider_type,
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


@router.post(
    "/{provider_id}/identity-domains",
    response_model=BaseResponse[IdentityBindingAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_identity_domain_binding(
    provider_id: uuid.UUID,
    body: IdentityDomainBindingCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[IdentityBindingAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    binding, operation = await _binding_service(uow).create_domain(
        provider_id,
        body,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
    )
    await uow.commit()
    return api_success(
        IdentityBindingAccepted(
            binding=IdentityBindingView.model_validate(binding, from_attributes=True),
            operation=operation,
            status_url=admin_operation_status_url(operation.id),
        ),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/{provider_id}/identity-projects",
    response_model=BaseResponse[IdentityBindingAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_identity_project_binding(
    provider_id: uuid.UUID,
    body: IdentityProjectBindingCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[IdentityBindingAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    binding, operation = await _binding_service(uow).create_project(
        provider_id,
        body,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
    )
    await uow.commit()
    return api_success(
        IdentityBindingAccepted(
            binding=IdentityBindingView.model_validate(binding, from_attributes=True),
            operation=operation,
            status_url=admin_operation_status_url(operation.id),
        ),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/{provider_id}", response_model=BaseResponse[ProviderView])
async def get_provider(
    provider_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ProviderView]:
    return api_success(await _service(uow).get(provider_id))


@router.patch("/{provider_id}", response_model=BaseResponse[ProviderView])
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderPatch,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ProviderView]:
    if uow.session.info["credential_cipher"] is None:
        raise CredentialKeyUnavailableError
    result = await _service(uow).update(provider_id, body.expected_version, body)
    await uow.commit()
    return api_success(result)
