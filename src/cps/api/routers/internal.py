"""Internal service-boundary routes; excluded from the public OpenAPI document."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.application.resolver import CredentialResolver
from cps.contracts.validation import CredentialResolution
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(include_in_schema=False)


async def internal_boundary() -> None:
    """No-op service-boundary hook reserved for mTLS/service authentication."""


@router.get(
    "/internal/v1/credentials/{credential_reference}",
    response_model=CredentialResolution,
    response_model_exclude={"schema_version"},
    dependencies=[Depends(internal_boundary)],
)
async def resolve_credential(
    credential_reference: uuid.UUID,
    provider_connection_id: uuid.UUID = Query(...),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CredentialResolution:
    cipher = uow.session.info["credential_cipher"]
    if cipher is None:
        from cps.contracts.errors import CredentialKeyUnavailableError

        raise CredentialKeyUnavailableError
    return await CredentialResolver(uow.providers, cipher).resolve(
        credential_reference, provider_connection_id
    )
