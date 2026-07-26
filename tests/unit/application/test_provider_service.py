"""Provider aggregate application service tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.api.schemas.providers import ProviderCreate, ProviderPatch
from cps.application.providers import ProviderService
from cps.contracts.errors import (
    CredentialKeyUnavailableError,
    ProviderNotFoundError,
    VersionConflictError,
)
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus, ProviderStatus
from cps.infrastructure.db.repositories.providers import ProviderVersionConflictError
from cps.security.credentials import (
    AesGcmCredentialCipher,
    MappingCredentialKeyProvider,
)

_TEST_KEY = b"c" * 32
_KEY_VERSION = "v1"
_PASSWORD = "synthetic-admin-password"  # pragma: allowlist secret
_USERNAME = "cloud-admin"
_AUTH_URL = "https://keystone.example/v3"


def _cipher() -> AesGcmCredentialCipher:
    return AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))


def _create_body() -> ProviderCreate:
    return ProviderCreate.model_validate(
        {
            "name": "lab-openstack",
            "provider_type": "OPENSTACK",
            "auth_url": _AUTH_URL,
            "username": _USERNAME,
            "password": _PASSWORD,
            "user_domain_name": "Default",
            "region_name": "RegionOne",
        }
    )


@pytest.mark.asyncio
async def test_create_persists_aggregate_and_redacts_public_view() -> None:
    stored: dict[str, object] = {}

    class Repository:
        async def provider_name_exists(self, _name: str, *, exclude_id=None) -> bool:
            return False

        async def add_provider_aggregate(self, command) -> SimpleNamespace:
            stored["command"] = command
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=command.provider_id,
                name=command.name,
                provider_type="OPENSTACK",
                description=command.description,
                status=ProviderStatus.ACTIVE,
                version=1,
                created_at=now,
                updated_at=now,
            )

        async def get_provider_aggregate(self, provider_id: uuid.UUID):
            now = datetime.now(UTC)
            command = stored["command"]
            credential_id = command.credential_id
            return (
                SimpleNamespace(
                    id=provider_id,
                    name=command.name,
                    provider_type="OPENSTACK",
                    description=command.description,
                    status=ProviderStatus.ACTIVE,
                    version=1,
                    created_at=now,
                    updated_at=now,
                ),
                SimpleNamespace(
                    id=command.connection_id,
                    provider_id=provider_id,
                    credential_id=credential_id,
                    scope_kind=ConnectionScopeKind.SYSTEM,
                    auth_url=command.auth_url,
                    region_name=command.region_name,
                    interface=command.interface,
                    verify_tls=command.verify_tls,
                    ca_cert_pem=command.ca_cert_pem,
                    status=ConnectionStatus.PENDING_VALIDATION,
                ),
                SimpleNamespace(
                    id=credential_id,
                    user_domain_name=command.user_domain_name,
                    username_ciphertext=command.encrypted_username.ciphertext,
                    username_nonce=command.encrypted_username.nonce,
                    password_ciphertext=command.encrypted_password.ciphertext,
                    password_nonce=command.encrypted_password.nonce,
                    encryption_key_version=command.encrypted_password.key_version,
                ),
            )

    service = ProviderService(Repository(), _cipher(), _KEY_VERSION)
    view = await service.create(_create_body())

    command = stored["command"]
    assert command.encrypted_password.ciphertext != _PASSWORD.encode()
    assert view.auth_url == _AUTH_URL
    assert view.user_domain_name == "Default"
    assert not hasattr(view, "password")
    dumped = view.model_dump(mode="json")
    assert "password" not in dumped
    assert "username" not in dumped
    assert "ciphertext" not in dumped


@pytest.mark.asyncio
async def test_create_fails_closed_without_cipher() -> None:
    class Repository:
        async def provider_name_exists(self, _name: str, *, exclude_id=None) -> bool:
            return False

    service = ProviderService(Repository(), None, _KEY_VERSION)
    with pytest.raises(CredentialKeyUnavailableError):
        await service.create(_create_body())


@pytest.mark.asyncio
async def test_update_can_rotate_password_without_public_exposure() -> None:
    provider_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    cipher = _cipher()
    encrypted_password = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PASSWORD,
        key_version=_KEY_VERSION,
    )
    encrypted_username = cipher.encrypt_secret(
        credential_id=credential_id,
        field_label="username",
        plaintext=_USERNAME,
        key_version=_KEY_VERSION,
    )
    now = datetime.now(UTC)
    aggregate = (
        SimpleNamespace(
            id=provider_id,
            name="lab-openstack",
            provider_type="OPENSTACK",
            description=None,
            status=ProviderStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        ),
        SimpleNamespace(
            id=connection_id,
            provider_id=provider_id,
            credential_id=credential_id,
            scope_kind=ConnectionScopeKind.SYSTEM,
            auth_url=_AUTH_URL,
            region_name="RegionOne",
            interface="public",
            verify_tls=True,
            ca_cert_pem=None,
            status=ConnectionStatus.VALID,
            version=2,
        ),
        SimpleNamespace(
            id=credential_id,
            user_domain_name="Default",
            username_ciphertext=encrypted_username.ciphertext,
            username_nonce=encrypted_username.nonce,
            password_ciphertext=encrypted_password.ciphertext,
            password_nonce=encrypted_password.nonce,
            encryption_key_version=_KEY_VERSION,
            version=1,
        ),
    )
    rotated_password = "rotated-admin-password"  # pragma: allowlist secret

    class Repository:
        async def get_provider_aggregate(self, _provider_id: uuid.UUID):
            return aggregate

        async def provider_name_exists(self, _name: str, *, exclude_id=None) -> bool:
            return False

        async def update_provider(self, *_args, **_kwargs):
            provider, connection, credential = aggregate
            return provider

        async def update_credential(self, *_args, **_kwargs):
            provider, connection, credential = aggregate
            return credential

        async def update_connection(self, *_args, **_kwargs):
            provider, connection, credential = aggregate
            connection.status = ConnectionStatus.PENDING_VALIDATION
            return connection

        async def increment_provider_version(self, _provider_id, *, expected_version):
            provider, connection, credential = aggregate
            provider.version = expected_version + 1
            return provider

    service = ProviderService(Repository(), cipher, _KEY_VERSION)
    view = await service.update(
        provider_id,
        1,
        ProviderPatch.model_validate(
            {
                "expected_version": 1,
                "password": rotated_password,
            }
        ),
    )
    assert view.connection_status is ConnectionStatus.PENDING_VALIDATION
    dumped = view.model_dump(mode="json")
    assert rotated_password not in dumped.values()


@pytest.mark.asyncio
async def test_metadata_only_update_increments_provider_version_once() -> None:
    provider_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    cipher = _cipher()
    encrypted_password = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PASSWORD,
        key_version=_KEY_VERSION,
    )
    encrypted_username = cipher.encrypt_secret(
        credential_id=credential_id,
        field_label="username",
        plaintext=_USERNAME,
        key_version=_KEY_VERSION,
    )
    now = datetime.now(UTC)
    provider_version = {"value": 1}
    increment_calls = {"count": 0}
    new_auth_url = "https://keystone.example/v3/updated"

    def _provider() -> SimpleNamespace:
        return SimpleNamespace(
            id=provider_id,
            name="lab-openstack",
            provider_type="OPENSTACK",
            description=None,
            status=ProviderStatus.ACTIVE,
            version=provider_version["value"],
            created_at=now,
            updated_at=now,
        )

    connection = SimpleNamespace(
        id=connection_id,
        provider_id=provider_id,
        credential_id=credential_id,
        scope_kind=ConnectionScopeKind.SYSTEM,
        auth_url=_AUTH_URL,
        region_name="RegionOne",
        interface="public",
        verify_tls=True,
        ca_cert_pem=None,
        status=ConnectionStatus.VALID,
        version=1,
    )
    credential = SimpleNamespace(
        id=credential_id,
        user_domain_name="Default",
        username_ciphertext=encrypted_username.ciphertext,
        username_nonce=encrypted_username.nonce,
        password_ciphertext=encrypted_password.ciphertext,
        password_nonce=encrypted_password.nonce,
        encryption_key_version=_KEY_VERSION,
        version=1,
    )

    class Repository:
        async def get_provider_aggregate(self, _provider_id: uuid.UUID):
            return _provider(), connection, credential

        async def provider_name_exists(self, _name: str, *, exclude_id=None) -> bool:
            return False

        async def update_connection(self, _connection_id, *, expected_version, values):
            connection.auth_url = values.get("auth_url", connection.auth_url)
            connection.status = values["status"]
            connection.version = expected_version + 1
            return connection

        async def increment_provider_version(self, _provider_id, *, expected_version):
            increment_calls["count"] += 1
            if provider_version["value"] != expected_version:
                raise ProviderVersionConflictError
            provider_version["value"] = expected_version + 1
            return _provider()

    service = ProviderService(Repository(), cipher, _KEY_VERSION)
    view = await service.update(
        provider_id,
        1,
        ProviderPatch.model_validate(
            {
                "expected_version": 1,
                "auth_url": new_auth_url,
            }
        ),
    )

    assert increment_calls["count"] == 1
    assert provider_version["value"] == 2
    assert view.version == 2
    assert view.auth_url == new_auth_url

    with pytest.raises(VersionConflictError):
        await service.update(
            provider_id,
            1,
            ProviderPatch.model_validate(
                {
                    "expected_version": 1,
                    "region_name": "RegionTwo",
                }
            ),
        )


@pytest.mark.asyncio
async def test_get_missing_aggregate_raises_not_found() -> None:
    class Repository:
        async def get_provider_aggregate(self, _provider_id: uuid.UUID):
            return None

    service = ProviderService(Repository(), _cipher(), _KEY_VERSION)
    with pytest.raises(ProviderNotFoundError):
        await service.get(uuid.uuid4())
