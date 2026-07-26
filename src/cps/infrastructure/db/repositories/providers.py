"""Provider persistence repositories."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cps.infrastructure.db.models.enums import (
    ConnectionScopeKind,
    ConnectionStatus,
    ProviderStatus,
)
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.security.credentials import EncryptedPassword, EncryptedSecret

_CONNECTION_IDENTITY_CONSTRAINT = "uq_provider_connections_provider_domain_project_region"


class DuplicateProviderConnectionError(Exception):
    """Raised when a provider connection identity already exists."""


class ProviderPersistenceError(Exception):
    """Raised when provider persistence fails for a non-duplicate reason."""


class ProviderVersionConflictError(Exception):
    """Raised when an optimistic provider update loses a race."""


class ConnectionVersionConflictError(Exception):
    """Raised when an optimistic connection update loses a race."""


class ProviderNameConflictError(Exception):
    """Raised when a provider name is already in use."""


@dataclass(frozen=True, slots=True)
class AddProviderCommand:
    provider_id: uuid.UUID
    name: str
    description: str | None = None
    status: ProviderStatus = ProviderStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class AddProviderAggregateCommand:
    provider_id: uuid.UUID
    connection_id: uuid.UUID
    name: str
    description: str | None
    encrypted_username: EncryptedSecret
    encrypted_password: EncryptedPassword
    user_domain_name: str
    auth_url: str
    region_name: str
    project_name: str = "admin"
    project_domain_name: str = "Default"
    interface: str = "public"
    verify_tls: bool = True
    ca_cert_pem: str | None = None
    status: ProviderStatus = ProviderStatus.ACTIVE

    @property
    def credential_id(self) -> uuid.UUID:
        """Legacy identity alias retained for callers during contract migration."""
        return self.provider_id


@dataclass(frozen=True, slots=True)
class AddConnectionCommand:
    connection_id: uuid.UUID
    provider_id: uuid.UUID
    project_name: str
    region_name: str
    auth_url: str
    scope_kind: str = "PROJECT"
    scope_domain_provider_resource_id: str | None = None
    scope_project_provider_resource_id: str | None = None
    project_domain_name: str = "Default"
    interface: str = "public"
    verify_tls: bool = True
    ca_cert_pem: str | None = None
    status: ConnectionStatus = ConnectionStatus.PENDING_VALIDATION


class ProviderRepository:
    """Async repository for provider aggregate persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_provider(self, command: AddProviderCommand) -> Provider:
        provider = Provider(
            id=command.provider_id,
            name=command.name,
            description=command.description,
            status=command.status,
            username_ciphertext=b"test",
            username_nonce=b"\x00" * 12,
            password_ciphertext=b"test",
            password_nonce=b"\x01" * 12,
            encryption_key_version="test",
            user_domain_name="Default",
            version=1,
        )
        self._session.add(provider)
        await _flush_or_raise(self._session)
        return provider

    async def add_provider_aggregate(self, command: AddProviderAggregateCommand) -> Provider:
        provider = Provider(
            id=command.provider_id,
            name=command.name,
            description=command.description,
            status=command.status,
            username_ciphertext=command.encrypted_username.ciphertext,
            username_nonce=command.encrypted_username.nonce,
            password_ciphertext=command.encrypted_password.ciphertext,
            password_nonce=command.encrypted_password.nonce,
            encryption_key_version=command.encrypted_password.key_version,
            user_domain_name=command.user_domain_name,
            version=1,
        )
        connection = ProviderConnection(
            id=command.connection_id,
            provider_id=command.provider_id,
            scope_kind=ConnectionScopeKind.SYSTEM,
            project_name=command.project_name,
            project_domain_name=command.project_domain_name,
            region_name=command.region_name,
            auth_url=command.auth_url,
            interface=command.interface,
            verify_tls=command.verify_tls,
            ca_cert_pem=command.ca_cert_pem,
            status=ConnectionStatus.PENDING_VALIDATION,
            version=1,
        )
        self._session.add(provider)
        await _flush_or_raise(self._session)
        self._session.add(connection)
        await _flush_or_raise(self._session)
        return provider

    async def update_provider_credential(
        self,
        provider_id: uuid.UUID,
        *,
        expected_version: int,
        encrypted_username: EncryptedSecret,
        encrypted_password: EncryptedPassword,
        user_domain_name: str,
        rotated_at: datetime,
    ) -> Provider:
        result = await self._session.execute(
            update(Provider)
            .where(Provider.id == provider_id, Provider.version == expected_version)
            .values(
                username_ciphertext=encrypted_username.ciphertext,
                username_nonce=encrypted_username.nonce,
                password_ciphertext=encrypted_password.ciphertext,
                password_nonce=encrypted_password.nonce,
                encryption_key_version=encrypted_password.key_version,
                user_domain_name=user_domain_name,
                credential_rotated_at=rotated_at,
                version=Provider.version + 1,
            )
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            credential = await self.get_provider(provider_id)
            if credential is None:
                raise ProviderPersistenceError("provider not found")
            raise ProviderVersionConflictError
        await self._session.flush()
        credential = await self.get_provider(provider_id)
        if credential is None:
            raise ProviderPersistenceError("provider not found")
        return credential

    async def add_connection(self, command: AddConnectionCommand) -> ProviderConnection:
        connection = ProviderConnection(
            id=command.connection_id,
            provider_id=command.provider_id,
            scope_kind=command.scope_kind,
            scope_domain_provider_resource_id=command.scope_domain_provider_resource_id,
            scope_project_provider_resource_id=command.scope_project_provider_resource_id,
            project_name=command.project_name,
            project_domain_name=command.project_domain_name,
            region_name=command.region_name,
            auth_url=command.auth_url,
            interface=command.interface,
            verify_tls=command.verify_tls,
            ca_cert_pem=command.ca_cert_pem,
            status=command.status,
            version=1,
        )
        self._session.add(connection)
        await _flush_or_raise(self._session)
        return connection

    async def get_provider(self, provider_id: uuid.UUID) -> Provider | None:
        result = await self._session.execute(select(Provider).where(Provider.id == provider_id))
        return result.scalar_one_or_none()

    async def get_provider_aggregate(
        self, provider_id: uuid.UUID
    ) -> tuple[Provider, ProviderConnection] | None:
        result = await self._session.execute(
            select(ProviderConnection, Provider)
            .join(Provider, Provider.id == ProviderConnection.provider_id)
            .where(
                ProviderConnection.provider_id == provider_id,
                ProviderConnection.scope_kind == ConnectionScopeKind.SYSTEM,
            )
            .order_by(ProviderConnection.created_at.asc(), ProviderConnection.id.asc())
            .limit(1)
        )
        row = result.one_or_none()
        if row is not None:
            return row[1], row[0]
        return await self._get_legacy_single_connection_aggregate(provider_id)

    async def _get_legacy_single_connection_aggregate(
        self, provider_id: uuid.UUID
    ) -> tuple[Provider, ProviderConnection] | None:
        result = await self._session.execute(
            select(ProviderConnection, Provider)
            .join(Provider, Provider.id == ProviderConnection.provider_id)
            .where(ProviderConnection.provider_id == provider_id)
            .order_by(ProviderConnection.created_at.asc(), ProviderConnection.id.asc())
        )
        rows = result.all()
        if len(rows) != 1:
            return None
        connection, provider = rows[0]
        return provider, connection

    async def provider_name_exists(self, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        query = select(func.count()).select_from(Provider).where(Provider.name == name)
        if exclude_id is not None:
            query = query.where(Provider.id != exclude_id)
        result = await self._session.execute(query)
        return bool(result.scalar_one())

    async def list_providers(
        self,
        *,
        offset: int,
        limit: int,
        status: ProviderStatus | None = None,
        name: str | None = None,
        provider_type: str | None = None,
        sort: str = "name",
        order: str = "asc",
    ) -> tuple[list[Provider], int]:
        query = select(Provider)
        count_query = select(func.count()).select_from(Provider)
        filters = []
        if status is not None:
            filters.append(Provider.status == status)
        if name is not None:
            filters.append(Provider.name.ilike(f"%{name}%"))
        if provider_type is not None:
            filters.append(Provider.provider_type == provider_type)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
        sort_column = {
            "name": Provider.name,
            "created_at": Provider.created_at,
            "updated_at": Provider.updated_at,
        }.get(sort, Provider.name)
        direction = sort_column.asc() if order == "asc" else sort_column.desc()
        tie_breaker = Provider.id.asc() if order == "asc" else Provider.id.desc()
        query = query.order_by(direction, tie_breaker).offset(offset).limit(limit)
        rows = await self._session.execute(query)
        total = await self._session.scalar(count_query)
        return list(rows.scalars().all()), int(total or 0)

    async def update_provider(
        self,
        provider_id: uuid.UUID,
        *,
        expected_version: int,
        name: str | None = None,
        description: str | None = None,
        description_set: bool = False,
        status: ProviderStatus | None = None,
    ) -> Provider:
        values: dict[str, object] = {}
        if name is not None:
            values["name"] = name
        if description_set:
            values["description"] = description
        if status is not None:
            values["status"] = status
        if not values:
            provider = await self.get_provider(provider_id)
            if provider is None:
                raise ProviderPersistenceError("provider not found")
            if provider.version != expected_version:
                raise ProviderVersionConflictError
            return provider
        result = await self._session.execute(
            update(Provider)
            .where(Provider.id == provider_id, Provider.version == expected_version)
            .values(**values, version=Provider.version + 1)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            provider = await self.get_provider(provider_id)
            if provider is None:
                raise ProviderPersistenceError("provider not found")
            raise ProviderVersionConflictError
        await self._session.flush()
        refreshed = await self.get_provider(provider_id)
        if refreshed is None:
            raise ProviderPersistenceError("provider not found")
        return refreshed

    async def increment_provider_version(
        self, provider_id: uuid.UUID, *, expected_version: int
    ) -> Provider:
        result = await self._session.execute(
            update(Provider)
            .where(Provider.id == provider_id, Provider.version == expected_version)
            .values(version=Provider.version + 1)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            provider = await self.get_provider(provider_id)
            if provider is None:
                raise ProviderPersistenceError("provider not found")
            raise ProviderVersionConflictError
        await self._session.flush()
        refreshed = await self.get_provider(provider_id)
        if refreshed is None:
            raise ProviderPersistenceError("provider not found")
        return refreshed

    async def get_connection(self, connection_id: uuid.UUID) -> ProviderConnection | None:
        result = await self._session.execute(
            select(ProviderConnection).where(ProviderConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def list_connections(
        self,
        *,
        offset: int,
        limit: int,
        provider_id: uuid.UUID | None = None,
        status: ConnectionStatus | None = None,
        sort: str = "created_at",
        order: str = "asc",
    ) -> tuple[list[ProviderConnection], int]:
        filters = []
        if provider_id is not None:
            filters.append(ProviderConnection.provider_id == provider_id)
        if status is not None:
            filters.append(ProviderConnection.status == status)
        query = select(ProviderConnection).where(*filters)
        count_query = select(func.count()).select_from(ProviderConnection).where(*filters)
        column = {
            "created_at": ProviderConnection.created_at,
            "updated_at": ProviderConnection.updated_at,
        }.get(sort, ProviderConnection.created_at)
        direction = column.asc() if order == "asc" else column.desc()
        tie = ProviderConnection.id.asc() if order == "asc" else ProviderConnection.id.desc()
        result = await self._session.execute(
            query.order_by(direction, tie).offset(offset).limit(limit)
        )
        total = await self._session.scalar(count_query)
        return list(result.scalars().all()), int(total or 0)

    async def get_connection_provider(
        self, connection_id: uuid.UUID
    ) -> tuple[ProviderConnection, Provider] | None:
        result = await self._session.execute(
            select(ProviderConnection, Provider)
            .join(Provider, Provider.id == ProviderConnection.provider_id)
            .where(
                ProviderConnection.id == connection_id,
            )
        )
        row = result.one_or_none()
        return row if row is None else (row[0], row[1])

    async def update_connection(
        self, connection_id: uuid.UUID, *, expected_version: int, values: dict[str, object]
    ) -> ProviderConnection:
        result = await self._session.execute(
            update(ProviderConnection)
            .where(
                ProviderConnection.id == connection_id,
                ProviderConnection.version == expected_version,
            )
            .values(**values, version=ProviderConnection.version + 1)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            connection = await self.get_connection(connection_id)
            if connection is None:
                raise ProviderPersistenceError("connection not found")
            raise ConnectionVersionConflictError
        await self._session.flush()
        connection = await self.get_connection(connection_id)
        if connection is None:
            raise ProviderPersistenceError("connection not found")
        return connection


async def _flush_or_raise(session: AsyncSession) -> None:
    database_error: DBAPIError | None = None
    try:
        await session.flush()
    except DBAPIError as exc:
        database_error = exc
    if database_error is not None:
        _raise_from_database_error(database_error)


def _extract_constraint_name(exc: DBAPIError) -> str | None:
    orig = exc.orig
    if orig is None:
        return None
    diag = getattr(orig, "diag", None)
    if diag is None:
        return None
    return getattr(diag, "constraint_name", None)


def _raise_from_database_error(exc: DBAPIError) -> NoReturn:
    if (
        isinstance(exc, IntegrityError)
        and _extract_constraint_name(exc) == _CONNECTION_IDENTITY_CONSTRAINT
    ):
        msg = "provider connection identity already exists"
        raise DuplicateProviderConnectionError(msg) from None
    msg = "provider persistence failed"
    raise ProviderPersistenceError(msg) from None
