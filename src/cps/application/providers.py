"""Provider CRUD application service."""

from __future__ import annotations

import uuid

from cps.api.schemas.providers import (
    PageInfo,
    ProviderCreate,
    ProviderPage,
    ProviderPatch,
    ProviderView,
)
from cps.contracts.errors import (
    ProviderNameConflictError,
    ProviderNotFoundError,
    VersionConflictError,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ProviderStatus
from cps.infrastructure.db.repositories.providers import (
    AddProviderCommand,
    ProviderPersistenceError,
    ProviderRepository,
    ProviderVersionConflictError,
)


def to_view(provider: object) -> ProviderView:
    return ProviderView.model_validate(provider, from_attributes=True)


class ProviderService:
    def __init__(self, repository: ProviderRepository) -> None:
        self._repository = repository

    async def create(self, command: ProviderCreate) -> ProviderView:
        if await self._repository.provider_name_exists(command.name):
            raise ProviderNameConflictError
        provider = await self._repository.add_provider(
            AddProviderCommand(
                provider_id=new_uuid7(),
                name=command.name,
                description=command.description,
            )
        )
        return to_view(provider)

    async def get(self, provider_id: uuid.UUID) -> ProviderView:
        provider = await self._repository.get_provider(provider_id)
        if provider is None:
            raise ProviderNotFoundError
        return to_view(provider)

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        status: ProviderStatus | None = None,
        name: str | None = None,
        provider_type: str | None = None,
        sort: str = "name",
        order: str = "asc",
    ) -> ProviderPage:
        providers, total = await self._repository.list_providers(
            offset=offset,
            limit=limit,
            status=status,
            name=name,
            provider_type=provider_type,
            sort=sort,
            order=order,
        )
        return ProviderPage(
            items=[to_view(provider) for provider in providers],
            page=PageInfo(offset=offset, limit=limit, total=total),
        )

    async def update(
        self, provider_id: uuid.UUID, expected_version: int, patch: ProviderPatch
    ) -> ProviderView:
        if patch.name is not None and await self._repository.provider_name_exists(
            patch.name, exclude_id=provider_id
        ):
            raise ProviderNameConflictError
        try:
            provider = await self._repository.update_provider(
                provider_id,
                expected_version=patch.expected_version,
                name=patch.name,
                description=patch.description,
                description_set="description" in patch.model_fields_set,
                status=patch.status,
            )
        except ProviderVersionConflictError as exc:
            raise VersionConflictError from exc
        except ProviderPersistenceError as exc:
            raise ProviderNotFoundError from exc
        return to_view(provider)
