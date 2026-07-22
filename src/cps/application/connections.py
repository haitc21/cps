"""Provider connection lifecycle service."""

from __future__ import annotations

import uuid

from cps.api.schemas.connections import (
    ConnectionCreate,
    ConnectionPage,
    ConnectionPatch,
    ConnectionView,
    PageInfo,
)
from cps.contracts.errors import (
    CredentialNotFoundError,
    ProviderConnectionConflictError,
    ProviderConnectionNotFoundError,
    ProviderNotFoundError,
    VersionConflictError,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.repositories.providers import (
    AddConnectionCommand,
    ConnectionVersionConflictError,
    DuplicateProviderConnectionError,
    ProviderPersistenceError,
    ProviderRepository,
)


def to_view(connection: ProviderConnection) -> ConnectionView:
    return ConnectionView.model_validate(
        {
            "id": connection.id,
            "provider_id": connection.provider_id,
            "project_name": connection.project_name,
            "project_domain_name": connection.project_domain_name,
            "region_name": connection.region_name,
            "auth_url": connection.auth_url,
            "interface": connection.interface,
            "verify_tls": connection.verify_tls,
            "has_custom_ca": bool(connection.ca_cert_pem),
            "status": connection.status,
            "capabilities": connection.capabilities,
            "validation_error": connection.validation_error,
            "validated_at": connection.validated_at,
            "version": connection.version,
            "created_at": connection.created_at,
            "updated_at": connection.updated_at,
        }
    )


class ConnectionService:
    def __init__(self, repository: ProviderRepository) -> None:
        self._repository = repository

    async def create(self, provider_id: uuid.UUID, body: ConnectionCreate) -> ConnectionView:
        provider = await self._repository.get_provider(provider_id)
        if provider is None:
            raise ProviderNotFoundError
        if provider.status != ProviderStatus.ACTIVE:
            raise ProviderConnectionConflictError("Provider is disabled")
        if await self._repository.get_credential(body.credential_id) is None:
            from cps.contracts.errors import CredentialNotFoundError

            raise CredentialNotFoundError
        try:
            connection = await self._repository.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(), provider_id=provider_id, **body.model_dump()
                )
            )
        except DuplicateProviderConnectionError as exc:
            raise ProviderConnectionConflictError from exc
        return to_view(connection)

    async def get(self, connection_id: uuid.UUID) -> ConnectionView:
        connection = await self._repository.get_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        return to_view(connection)

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        provider_id: uuid.UUID | None = None,
        status: ConnectionStatus | None = None,
        sort: str = "created_at",
        order: str = "asc",
    ) -> ConnectionPage:
        rows, total = await self._repository.list_connections(
            offset=offset,
            limit=limit,
            provider_id=provider_id,
            status=status,
            sort=sort,
            order=order,
        )
        return ConnectionPage(
            items=[to_view(row) for row in rows],
            page=PageInfo(offset=offset, limit=limit, total=total),
        )

    async def update(self, connection_id: uuid.UUID, body: ConnectionPatch) -> ConnectionView:
        connection = await self._repository.get_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        if connection.version != body.expected_version:
            raise VersionConflictError
        changes = body.model_dump(exclude={"expected_version"}, exclude_unset=True)
        if (
            "credential_id" in changes
            and await self._repository.get_credential(changes["credential_id"]) is None
        ):
            raise CredentialNotFoundError
        material = {
            "credential_id",
            "auth_url",
            "project_name",
            "project_domain_name",
            "region_name",
            "interface",
            "verify_tls",
            "ca_cert_pem",
        }
        if material.intersection(changes):
            changes.update(
                status=ConnectionStatus.PENDING_VALIDATION,
                capabilities=None,
                validation_error=None,
                validated_at=None,
            )
        try:
            updated = await self._repository.update_connection(
                connection_id, expected_version=body.expected_version, values=changes
            )
        except ConnectionVersionConflictError as exc:
            raise VersionConflictError from exc
        except ProviderPersistenceError as exc:
            raise ProviderConnectionNotFoundError from exc
        return to_view(updated)
