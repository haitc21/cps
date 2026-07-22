"""Public credential lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from cps.api.dependencies import get_uow
from cps.api.schemas.credentials import CredentialCreate, CredentialMetadataView, CredentialPatch
from cps.application.credentials import CredentialService
from cps.config import Settings
from cps.contracts.errors import CredentialKeyUnavailableError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


def _service(uow: SqlAlchemyUnitOfWork) -> CredentialService:
    settings: Settings = uow.session.info["settings"]
    cipher = uow.session.info["credential_cipher"]
    if cipher is None:
        raise CredentialKeyUnavailableError
    return CredentialService(uow.providers, cipher, settings.credential_active_key_version)


@router.post("", response_model=CredentialMetadataView, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CredentialMetadataView:
    result = await _service(uow).create(body)
    await uow.commit()
    return result


@router.patch("/{credential_id}", response_model=CredentialMetadataView)
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialPatch,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> CredentialMetadataView:
    result = await _service(uow).update(credential_id, body)
    await uow.commit()
    return result


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> None:
    await _service(uow).delete(credential_id)
    await uow.commit()
