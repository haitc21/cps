"""Provider-level internal credential resolution tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from cps.application.resolver import CredentialResolver
from cps.contracts.errors import ProviderNotFoundError
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus, ProviderStatus
from cps.security.credentials import (
    AesGcmCredentialCipher,
    MappingCredentialKeyProvider,
)

_TEST_KEY = b"d" * 32
_KEY_VERSION = "v1"
_PASSWORD = "synthetic-admin-password"  # pragma: allowlist secret
_USERNAME = "cloud-admin"
_AUTH_URL = "https://keystone.example/v3"


def _build_aggregate(provider_id: uuid.UUID):
    credential_id = uuid.uuid4()
    cipher = AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))
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
    return (
        SimpleNamespace(id=provider_id, status=ProviderStatus.ACTIVE),
        SimpleNamespace(
            id=uuid.uuid4(),
            provider_id=provider_id,
            credential_id=credential_id,
            scope_kind=ConnectionScopeKind.SYSTEM,
            auth_url=_AUTH_URL,
            project_name="__system__",
            project_domain_name="Default",
            region_name="RegionOne",
            interface="public",
            verify_tls=True,
            ca_cert_pem=None,
            status=ConnectionStatus.VALID,
        ),
        SimpleNamespace(
            id=credential_id,
            user_domain_name="Default",
            username_ciphertext=encrypted_username.ciphertext,
            username_nonce=encrypted_username.nonce,
            password_ciphertext=encrypted_password.ciphertext,
            password_nonce=encrypted_password.nonce,
            encryption_key_version=_KEY_VERSION,
        ),
    )


@pytest.mark.asyncio
async def test_resolve_by_provider_id_returns_decrypted_credentials() -> None:
    provider_id = uuid.uuid4()
    aggregate = _build_aggregate(provider_id)
    cipher = AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))

    class Repository:
        async def get_provider_aggregate(self, requested_id: uuid.UUID):
            if requested_id != provider_id:
                return None
            return aggregate

    resolved = await CredentialResolver(Repository(), cipher).resolve_by_provider_id(provider_id)
    assert resolved.username == _USERNAME
    assert resolved.password == _PASSWORD
    assert resolved.auth_url == _AUTH_URL


@pytest.mark.asyncio
async def test_resolve_by_provider_id_missing_aggregate_is_not_found() -> None:
    cipher = AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))

    class Repository:
        async def get_provider_aggregate(self, _provider_id: uuid.UUID):
            return None

    with pytest.raises(ProviderNotFoundError):
        await CredentialResolver(Repository(), cipher).resolve_by_provider_id(uuid.uuid4())
