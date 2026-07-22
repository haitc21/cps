"""Internal, non-cached credential resolution."""

from __future__ import annotations

import uuid

from cps.contracts.errors import (
    CredentialKeyUnavailableError,
    CredentialNotFoundError,
    ProviderConnectionNotFoundError,
)
from cps.contracts.validation import CredentialResolution
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
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

    async def resolve(
        self, credential_id: uuid.UUID, provider_connection_id: uuid.UUID
    ) -> CredentialResolution:
        row = await self._repository.get_connection_credential(
            provider_connection_id, credential_id
        )
        if row is None:
            raise CredentialNotFoundError
        connection, provider, credential = row
        if (
            provider.status != ProviderStatus.ACTIVE
            or connection.status == ConnectionStatus.DISABLED
        ):
            raise ProviderConnectionNotFoundError
        try:
            username = self._cipher.decrypt_secret(
                credential_id=credential.id,
                field_label="username",
                encrypted=EncryptedSecret(
                    ciphertext=credential.username_ciphertext,
                    nonce=credential.username_nonce,
                    key_version=credential.encryption_key_version,
                ),
            )
            password = self._cipher.decrypt_password(
                credential_id=credential.id,
                encrypted=EncryptedPassword(
                    ciphertext=credential.password_ciphertext,
                    nonce=credential.password_nonce,
                    key_version=credential.encryption_key_version,
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
                "user_domain_name": credential.user_domain_name,
                "project_name": connection.project_name,
                "project_domain_name": connection.project_domain_name,
                "region_name": connection.region_name,
                "interface": connection.interface,
                "verify_tls": connection.verify_tls,
                "ca_cert_pem": connection.ca_cert_pem,
            }
        )
