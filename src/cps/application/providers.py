"""Provider CRUD application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cps.api.schemas.providers import (
    PageInfo,
    ProviderCreate,
    ProviderPage,
    ProviderPatch,
    ProviderView,
)
from cps.contracts.errors import (
    CredentialKeyUnavailableError,
    ProviderNameConflictError,
    ProviderNotFoundError,
    VersionConflictError,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.providers import (
    AddProviderAggregateCommand,
    ConnectionVersionConflictError,
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


def to_view(
    provider: Provider,
    *,
    connection: ProviderConnection,
) -> ProviderView:
    return ProviderView.model_validate(
        {
            "id": provider.id,
            "name": provider.name,
            "provider_type": provider.provider_type,
            "description": provider.description,
            "status": provider.status,
            "version": provider.version,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
            "auth_url": connection.auth_url,
            "user_domain_name": getattr(provider, "user_domain_name", "Default"),
            "region_name": connection.region_name,
            "interface": connection.interface,
            "verify_tls": connection.verify_tls,
            "has_custom_ca": bool(connection.ca_cert_pem),
            "connection_status": connection.status,
        }
    )


class ProviderService:
    def __init__(
        self,
        repository: ProviderRepository,
        cipher: AesGcmCredentialCipher | None = None,
        active_key_version: str = "v1",
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._active_key = active_key_version

    async def create(self, command: ProviderCreate) -> ProviderView:
        if self._cipher is None:
            raise CredentialKeyUnavailableError
        if await self._repository.provider_name_exists(command.name):
            raise ProviderNameConflictError
        provider_id = new_uuid7()
        connection_id = new_uuid7()
        try:
            encrypted_username = self._cipher.encrypt_secret(
                credential_id=provider_id,
                field_label="username",
                plaintext=command.username,
                key_version=self._active_key,
            )
            encrypted_password = self._cipher.encrypt_password(
                credential_id=provider_id,
                plaintext=command.password,
                key_version=self._active_key,
            )
        except CredentialEncryptionError as exc:
            raise CredentialKeyUnavailableError from exc
        provider = await self._repository.add_provider_aggregate(
            AddProviderAggregateCommand(
                provider_id=provider_id,
                connection_id=connection_id,
                name=command.name,
                description=command.description,
                encrypted_username=encrypted_username,
                encrypted_password=encrypted_password,
                user_domain_name=command.user_domain_name,
                project_name=command.project_name,
                project_domain_name=command.project_domain_name,
                auth_url=command.auth_url,
                region_name=command.region_name,
                interface=command.interface,
                verify_tls=command.verify_tls,
                ca_cert_pem=command.ca_cert_pem,
            )
        )
        aggregate = await self._repository.get_provider_aggregate(provider.id)
        if aggregate is None:
            raise ProviderNotFoundError
        provider_row, connection_row = aggregate[:2]
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
                    setattr(provider_row, field, getattr(legacy_credential, field))
            if hasattr(legacy_credential, "id"):
                provider_row._legacy_credential_id = legacy_credential.id
        return to_view(provider_row, connection=connection_row)

    async def get(self, provider_id: uuid.UUID) -> ProviderView:
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
        return to_view(provider, connection=connection)

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
        items: list[ProviderView] = []
        for provider in providers:
            aggregate = await self._repository.get_provider_aggregate(provider.id)
            if aggregate is None:
                continue
            connection = aggregate[1]
            items.append(to_view(provider, connection=connection))
        return ProviderPage(
            items=items,
            page=PageInfo(offset=offset, limit=limit, total=total),
        )

    async def update(
        self, provider_id: uuid.UUID, expected_version: int, patch: ProviderPatch
    ) -> ProviderView:
        if self._cipher is None:
            raise CredentialKeyUnavailableError
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
        if patch.name is not None and await self._repository.provider_name_exists(
            patch.name, exclude_id=provider_id
        ):
            raise ProviderNameConflictError
        if provider.version != expected_version:
            raise VersionConflictError
        provider_values: dict[str, object] = {}
        if patch.name is not None:
            provider_values["name"] = patch.name
        if "description" in patch.model_fields_set:
            provider_values["description"] = patch.description
        if patch.status is not None:
            provider_values["status"] = patch.status
        provider_metadata_changed = bool(provider_values)
        credential_changed = any(
            field in patch.model_fields_set
            for field in ("username", "password", "user_domain_name")
        )
        connection_changed = any(
            field in patch.model_fields_set
            for field in (
                "auth_url",
                "region_name",
                "interface",
                "verify_tls",
                "ca_cert_pem",
            )
        )
        aggregate_changed = credential_changed or connection_changed
        if provider_metadata_changed:
            try:
                provider = await self._repository.update_provider(
                    provider_id,
                    expected_version=expected_version,
                    name=patch.name,
                    description=patch.description,
                    description_set="description" in patch.model_fields_set,
                    status=patch.status,
                )
            except ProviderVersionConflictError as exc:
                raise VersionConflictError from exc
            except ProviderPersistenceError as exc:
                raise ProviderNotFoundError from exc
        if credential_changed:
            try:
                username = patch.username
                if username is None:
                    username = self._cipher.decrypt_secret(
                        credential_id=getattr(provider, "_legacy_credential_id", provider.id),
                        field_label="username",
                        encrypted=EncryptedSecret(
                            ciphertext=provider.username_ciphertext,
                            nonce=provider.username_nonce,
                            key_version=provider.encryption_key_version,
                        ),
                    )
                password = patch.password
                if password is None:
                    password = self._cipher.decrypt_password(
                        credential_id=getattr(provider, "_legacy_credential_id", provider.id),
                        encrypted=EncryptedPassword(
                            ciphertext=provider.password_ciphertext,
                            nonce=provider.password_nonce,
                            key_version=provider.encryption_key_version,
                        ),
                    )
                encrypted_username = self._cipher.encrypt_secret(
                    credential_id=provider.id,
                    field_label="username",
                    plaintext=username,
                    key_version=self._active_key,
                )
                encrypted_password = self._cipher.encrypt_password(
                    credential_id=provider.id,
                    plaintext=password,
                    key_version=self._active_key,
                )
            except CredentialEncryptionError as exc:
                raise CredentialKeyUnavailableError from exc
            try:
                update_credential = getattr(self._repository, "update_provider_credential", None)
                if update_credential is not None:
                    provider = await update_credential(
                        provider.id,
                        expected_version=provider.version,
                        encrypted_username=encrypted_username,
                        encrypted_password=encrypted_password,
                        user_domain_name=patch.user_domain_name or provider.user_domain_name,
                        rotated_at=datetime.now(UTC),
                    )
                else:  # compatibility for repositories during rolling upgrades
                    legacy_update = self._repository.update_credential  # type: ignore[attr-defined]
                    provider = await legacy_update(
                        provider.id, encrypted_username, encrypted_password
                    )
            except ProviderVersionConflictError as exc:
                raise VersionConflictError from exc
            except ProviderPersistenceError as exc:
                raise ProviderNotFoundError from exc
            connection_changed = True

        if connection_changed:
            values: dict[str, object] = {
                "status": ConnectionStatus.PENDING_VALIDATION,
                "capabilities": None,
                "validation_error": None,
                "validated_at": None,
            }
            if patch.auth_url is not None:
                values["auth_url"] = patch.auth_url
            if patch.region_name is not None:
                values["region_name"] = patch.region_name
            if patch.interface is not None:
                values["interface"] = patch.interface
            if patch.verify_tls is not None:
                values["verify_tls"] = patch.verify_tls
            if "ca_cert_pem" in patch.model_fields_set:
                values["ca_cert_pem"] = patch.ca_cert_pem
            try:
                connection = await self._repository.update_connection(
                    connection.id,
                    expected_version=connection.version,
                    values=values,
                )
            except ConnectionVersionConflictError as exc:
                raise VersionConflictError from exc
            except ProviderPersistenceError as exc:
                raise ProviderNotFoundError from exc

        if aggregate_changed and not provider_metadata_changed and not credential_changed:
            try:
                provider = await self._repository.increment_provider_version(
                    provider_id, expected_version=expected_version
                )
            except ProviderVersionConflictError as exc:
                raise VersionConflictError from exc
            except ProviderPersistenceError as exc:
                raise ProviderNotFoundError from exc

        final_aggregate = await self._repository.get_provider_aggregate(provider_id)
        if final_aggregate is not None:
            provider, connection = final_aggregate[:2]
            if len(final_aggregate) == 3:
                legacy_credential = final_aggregate[2]
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

        return to_view(provider, connection=connection)
