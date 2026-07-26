"""Provider aggregate persistence tests for provider-owned credentials."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.providers import (
    AddConnectionCommand,
    AddProviderAggregateCommand,
    DuplicateProviderConnectionError,
    ProviderPersistenceError,
)
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.credentials import AesGcmCredentialCipher, MappingCredentialKeyProvider

pytestmark = pytest.mark.integration

_KEY_VERSION = "v1"
_TEST_KEY = b"b" * 32
_PLAINTEXT = "synthetic-test-password-value"  # pragma: allowlist secret


@pytest.fixture
def cipher() -> AesGcmCredentialCipher:
    return AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))


async def _commit_provider_aggregate(db_session_factory, cipher):
    provider_id = new_uuid7()
    connection_id = new_uuid7()
    username = cipher.encrypt_secret(
        credential_id=provider_id,
        field_label="username",
        plaintext="service-user",
        key_version=_KEY_VERSION,
    )
    password = cipher.encrypt_password(
        credential_id=provider_id, plaintext=_PLAINTEXT, key_version=_KEY_VERSION
    )
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_provider_aggregate(
            AddProviderAggregateCommand(
                provider_id=provider_id,
                connection_id=connection_id,
                name="provider-one",
                encrypted_username=username,
                encrypted_password=password,
                user_domain_name="Default",
                auth_url="https://keystone.example/v3",
                region_name="RegionOne",
                project_name="demo",
            )
        )
        await uow.commit()
    return provider_id, connection_id


@pytest.mark.asyncio
async def test_insert_and_select_provider_aggregate(db_session_factory, cipher) -> None:
    provider_id, connection_id = await _commit_provider_aggregate(db_session_factory, cipher)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        provider, connection = await uow.providers.get_provider_aggregate(provider_id)
        assert provider.id == provider_id
        assert connection.id == connection_id
        assert connection.provider_id == provider_id
        assert provider.password_ciphertext != _PLAINTEXT.encode()


@pytest.mark.asyncio
async def test_provider_update_rotates_owned_credential(db_session_factory, cipher) -> None:
    provider_id, _ = await _commit_provider_aggregate(db_session_factory, cipher)
    rotated = cipher.encrypt_password(
        credential_id=provider_id, plaintext="rotated-password", key_version=_KEY_VERSION
    )
    username = cipher.encrypt_secret(
        credential_id=provider_id,
        field_label="username",
        plaintext="new-user",
        key_version=_KEY_VERSION,
    )
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        provider = await uow.providers.get_provider(provider_id)
        await uow.providers.update_provider_credential(
            provider_id,
            expected_version=provider.version,
            username_ciphertext=username.ciphertext,
            username_nonce=username.nonce,
            password_ciphertext=rotated.ciphertext,
            password_nonce=rotated.nonce,
            encryption_key_version=_KEY_VERSION,
        )
        await uow.commit()
    async with db_session_factory() as session:
        row = await session.scalar(select(Provider).where(Provider.id == provider_id))
        assert row is not None
        assert row.password_ciphertext == rotated.ciphertext


@pytest.mark.asyncio
async def test_duplicate_connection_identity_is_rejected(db_session_factory, cipher) -> None:
    provider_id, _ = await _commit_provider_aggregate(db_session_factory, cipher)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(DuplicateProviderConnectionError):
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=provider_id,
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url="https://keystone.example/v3",
                )
            )


@pytest.mark.asyncio
async def test_invalid_provider_foreign_key_is_not_duplicate_identity(db_session_factory) -> None:
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError):
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=new_uuid7(),
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url="https://keystone.example/v3",
                )
            )
