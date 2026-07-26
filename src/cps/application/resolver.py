"""Internal, non-cached credential resolution."""

from __future__ import annotations

import uuid

from cps.contracts.errors import (
    CredentialKeyUnavailableError,
    ProviderConnectionNotFoundError,
    ProviderNotFoundError,
)
from cps.contracts.validation import CredentialResolution
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.providers import ProviderRepository
from cps.security.credentials import (
    AesGcmCredentialCipher,
    CredentialEncryptionError,
    EncryptedPassword,
    EncryptedSecret,
)


class CredentialResolver:
    def __init__(self, repository: ProviderRepository, cipher: AesGcmCredentialCipher) -> None:
        self._repository = repository
        self._cipher = cipher

    async def resolve_by_provider_id(self, provider_id: uuid.UUID) -> CredentialResolution:
        aggregate = await self._repository.get_provider_aggregate(provider_id)
        if aggregate is None:
            raise ProviderNotFoundError
        provider, connection = aggregate[:2]
        if len(aggregate) == 3:
            legacy_credential = aggregate[2]
            for field in (
                "user_domain_name",
                "username_ciphertext",
                "username_nonce",
                "password_ciphertext",
                "password_nonce",
                "encryption_key_version",
            ):
                if hasattr(legacy_credential, field):
                    setattr(provider, field, getattr(legacy_credential, field))
            if hasattr(legacy_credential, "id"):
                provider._legacy_credential_id = legacy_credential.id
        if (
            provider.status != ProviderStatus.ACTIVE
            or connection.status == ConnectionStatus.DISABLED
        ):
            raise ProviderNotFoundError
        return self._build_resolution(provider, connection)

    async def resolve(self, provider_connection_id: uuid.UUID) -> CredentialResolution:
        row = await self._repository.get_connection_provider(provider_connection_id)
        if row is None:
            raise ProviderConnectionNotFoundError
        connection, provider = row
        if (
            provider.status != ProviderStatus.ACTIVE
            or connection.status == ConnectionStatus.DISABLED
        ):
            raise ProviderConnectionNotFoundError
        return self._build_resolution(provider, connection)

    def _build_resolution(
        self, provider: Provider, connection: ProviderConnection
    ) -> CredentialResolution:
        try:
            username = self._cipher.decrypt_secret(
                credential_id=getattr(provider, "_legacy_credential_id", provider.id),
                field_label="username",
                encrypted=EncryptedSecret(
                    ciphertext=provider.username_ciphertext,
                    nonce=provider.username_nonce,
                    key_version=provider.encryption_key_version,
                ),
            )
            password = self._cipher.decrypt_password(
                credential_id=getattr(provider, "_legacy_credential_id", provider.id),
                encrypted=EncryptedPassword(
                    ciphertext=provider.password_ciphertext,
                    nonce=provider.password_nonce,
                    key_version=provider.encryption_key_version,
                ),
            )
        except CredentialEncryptionError as exc:
            raise CredentialKeyUnavailableError from exc
        return CredentialResolution.model_validate(
            {
                "schema_version": "1.0",
                "auth_url": connection.auth_url,
                "username": username,
                "password": password,
                "user_domain_name": provider.user_domain_name,
                "scope_kind": connection.scope_kind.value,
                "project_name": connection.project_name,
                "project_domain_name": connection.project_domain_name,
                "region_name": connection.region_name,
                "interface": connection.interface,
                "verify_tls": connection.verify_tls,
                "ca_cert_pem": connection.ca_cert_pem,
            }
        )
