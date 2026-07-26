"""Internal service-boundary routes; excluded from the public OpenAPI document."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cps.api.dependencies import get_uow
from cps.application.resolver import CredentialResolver
from cps.contracts.validation import CredentialResolution
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(include_in_schema=False)


async def internal_boundary() -> None:
    """No-op service-boundary hook reserved for mTLS/service authentication."""


@router.get(
    "/internal/v1/connections/{provider_connection_id}/resolution",
    response_model=CredentialResolution,
    response_model_exclude={"schema_version"},
    dependencies=[Depends(internal_boundary)],
)
async def resolve_connection(
    provider_connection_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CredentialResolution:
    cipher = uow.session.info["credential_cipher"]
    if cipher is None:
        from cps.contracts.errors import CredentialKeyUnavailableError

        raise CredentialKeyUnavailableError
    return await CredentialResolver(uow.providers, cipher).resolve(provider_connection_id)


@router.get(
    "/internal/v1/providers/{provider_id}/resolution",
    response_model=CredentialResolution,
    response_model_exclude={"schema_version"},
    dependencies=[Depends(internal_boundary)],
)
async def resolve_provider(
    provider_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CredentialResolution:
    cipher = uow.session.info["credential_cipher"]
    if cipher is None:
        from cps.contracts.errors import CredentialKeyUnavailableError

        raise CredentialKeyUnavailableError
    return await CredentialResolver(uow.providers, cipher).resolve_by_provider_id(provider_id)
