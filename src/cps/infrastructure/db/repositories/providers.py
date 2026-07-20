"""Provider persistence repositories."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.security.credentials import EncryptedPassword

_CONNECTION_IDENTITY_CONSTRAINT = "uq_provider_connections_provider_domain_project_region"


class DuplicateProviderConnectionError(Exception):
    """Raised when a provider connection identity already exists."""


class ProviderPersistenceError(Exception):
    """Raised when provider persistence fails for a non-duplicate reason."""


@dataclass(frozen=True, slots=True)
class AddProviderCommand:
    provider_id: uuid.UUID
    name: str
    description: str | None = None
    status: ProviderStatus = ProviderStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class AddCredentialCommand:
    credential_id: uuid.UUID
    username: str
    encrypted_password: EncryptedPassword
    user_domain_name: str = "Default"


@dataclass(frozen=True, slots=True)
class AddConnectionCommand:
    connection_id: uuid.UUID
    provider_id: uuid.UUID
    credential_id: uuid.UUID
    project_name: str
    region_name: str
    auth_url: str
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
            version=1,
        )
        self._session.add(provider)
        await _flush_or_raise(self._session)
        return provider

    async def add_credential(self, command: AddCredentialCommand) -> Credential:
        credential = Credential(
            id=command.credential_id,
            username=command.username,
            password_ciphertext=command.encrypted_password.ciphertext,
            password_nonce=command.encrypted_password.nonce,
            encryption_key_version=command.encrypted_password.key_version,
            user_domain_name=command.user_domain_name,
            version=1,
        )
        self._session.add(credential)
        await _flush_or_raise(self._session)
        return credential

    async def add_connection(self, command: AddConnectionCommand) -> ProviderConnection:
        connection = ProviderConnection(
            id=command.connection_id,
            provider_id=command.provider_id,
            credential_id=command.credential_id,
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

    async def get_credential(self, credential_id: uuid.UUID) -> Credential | None:
        result = await self._session.execute(
            select(Credential).where(Credential.id == credential_id)
        )
        return result.scalar_one_or_none()

    async def get_connection(self, connection_id: uuid.UUID) -> ProviderConnection | None:
        result = await self._session.execute(
            select(ProviderConnection).where(ProviderConnection.id == connection_id)
        )
        return result.scalar_one_or_none()


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
