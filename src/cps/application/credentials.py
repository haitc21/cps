"""Credential lifecycle service with handler-scoped plaintext."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from cps.api.schemas.credentials import CredentialCreate, CredentialMetadataView, CredentialPatch
from cps.contracts.errors import (
    CredentialInUseError,
    CredentialKeyUnavailableError,
    CredentialNotFoundError,
    VersionConflictError,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.repositories.providers import (
    AddCredentialCommand,
    ProviderPersistenceError,
    ProviderRepository,
    ProviderVersionConflictError,
)
from cps.security.credentials import (
    AesGcmCredentialCipher,
    CredentialEncryptionError,
    EncryptedPassword,
    EncryptedSecret,
)


class CredentialService:
    def __init__(
        self, repository: ProviderRepository, cipher: AesGcmCredentialCipher, active_key: str
    ):
        self._repository = repository
        self._cipher = cipher
        self._active_key = active_key

    @staticmethod
    def _view(credential: object) -> CredentialMetadataView:
        return CredentialMetadataView.model_validate(credential, from_attributes=True)

    async def create(self, body: CredentialCreate) -> CredentialMetadataView:
        credential_id = new_uuid7()
        try:
            encrypted_username = self._cipher.encrypt_secret(
                credential_id=credential_id,
                field_label="username",
                plaintext=body.username,
                key_version=self._active_key,
            )
            encrypted_password = self._cipher.encrypt_password(
                credential_id=credential_id,
                plaintext=body.password,
                key_version=self._active_key,
            )
        except CredentialEncryptionError as exc:
            raise CredentialKeyUnavailableError from exc
        credential = await self._repository.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username=body.username,
                encrypted_username=encrypted_username,
                encrypted_password=encrypted_password,
                user_domain_name=body.user_domain_name,
            )
        )
        return self._view(credential)

    async def update(self, credential_id: UUID, body: CredentialPatch) -> CredentialMetadataView:
        credential = await self._repository.get_credential(credential_id)
        if credential is None:
            raise CredentialNotFoundError
        if credential.version != body.expected_version:
            raise VersionConflictError
        try:
            username = body.username
            if username is None:
                username = self._cipher.decrypt_secret(
                    credential_id=credential_id,
                    field_label="username",
                    encrypted=EncryptedSecret(
                        ciphertext=credential.username_ciphertext,
                        nonce=credential.username_nonce,
                        key_version=credential.encryption_key_version,
                    ),
                )
            password = body.password
            if password is None:
                password = self._cipher.decrypt_password(
                    credential_id=credential_id,
                    encrypted=EncryptedPassword(
                        ciphertext=credential.password_ciphertext,
                        nonce=credential.password_nonce,
                        key_version=credential.encryption_key_version,
                    ),
                )
            encrypted_username = self._cipher.encrypt_secret(
                credential_id=credential_id,
                field_label="username",
                plaintext=username,
                key_version=self._active_key,
            )
            encrypted_password = self._cipher.encrypt_password(
                credential_id=credential_id,
                plaintext=password,
                key_version=self._active_key,
            )
        except (CredentialEncryptionError, TypeError, ValueError) as exc:
            raise CredentialKeyUnavailableError from exc
        try:
            updated = await self._repository.update_credential(
                credential_id,
                expected_version=body.expected_version,
                encrypted_username=encrypted_username,
                encrypted_password=encrypted_password,
                user_domain_name=body.user_domain_name or credential.user_domain_name,
                rotated_at=datetime.now(UTC),
            )
        except ProviderVersionConflictError as exc:
            raise VersionConflictError from exc
        except ProviderPersistenceError as exc:
            raise CredentialNotFoundError from exc
        return self._view(updated)

    async def delete(self, credential_id: UUID) -> None:
        if await self._repository.get_credential(credential_id) is None:
            raise CredentialNotFoundError
        if await self._repository.credential_is_referenced(credential_id):
            raise CredentialInUseError
        try:
            await self._repository.delete_credential(credential_id)
        except ProviderPersistenceError as exc:
            raise CredentialNotFoundError from exc
