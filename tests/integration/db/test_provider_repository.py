"""CPS-103 Task 3: provider repository integration tests."""

from __future__ import annotations

import traceback
import uuid

import psycopg
import pytest
from sqlalchemy import select

from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.providers import (
    AddConnectionCommand,
    AddCredentialCommand,
    AddProviderCommand,
    DuplicateProviderConnectionError,
    ProviderPersistenceError,
)
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.credentials import (
    AesGcmCredentialCipher,
    MappingCredentialKeyProvider,
)

pytestmark = pytest.mark.integration

_TEST_KEY = b"b" * 32
_KEY_VERSION = "v1"
_PLAINTEXT = "synthetic-test-password-value"  # pragma: allowlist secret


_AUTH_URL = "https://keystone.example/v3"
_USERNAME = "service-user"


def _assert_redacted_persistence_exception(
    exc: BaseException,
    *,
    extra_forbidden: tuple[str, ...] = (),
) -> None:
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    forbidden = (
        "INSERT",
        "SELECT",
        "UPDATE",
        "DELETE",
        "postgresql",
        "psycopg",
        _AUTH_URL,
        _USERNAME,
        _PLAINTEXT,
        _TEST_KEY.hex(),
        "password_ciphertext",
        "provider_connections",
    )
    for fragment in (*forbidden, *extra_forbidden):
        assert fragment not in rendered
    assert exc.__cause__ is None
    assert exc.__context__ is None


@pytest.fixture
def cipher() -> AesGcmCredentialCipher:
    return AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: _TEST_KEY}))


async def _commit_provider_aggregate(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    connection_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_provider(
            AddProviderCommand(provider_id=provider_id, name="provider-one")
        )
        await uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username="service-user",
                encrypted_password=encrypted,
                encrypted_username=cipher.encrypt_secret(
                    credential_id=credential_id,
                    field_label="username",
                    plaintext="service-user",
                    key_version=_KEY_VERSION,
                ),
            )
        )
        await uow.providers.add_connection(
            AddConnectionCommand(
                connection_id=connection_id,
                provider_id=provider_id,
                credential_id=credential_id,
                project_name="demo",
                region_name="RegionOne",
                auth_url="https://keystone.example/v3",
            )
        )
        await uow.commit()

    return provider_id, credential_id, connection_id


@pytest.mark.asyncio
async def test_insert_and_select_provider_aggregate(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, connection_id = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )

    verify_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with verify_uow:
        provider = await verify_uow.providers.get_provider(provider_id)
        credential = await verify_uow.providers.get_credential(credential_id)
        connection = await verify_uow.providers.get_connection(connection_id)

        assert provider is not None
        assert credential is not None
        assert connection is not None
        assert connection.provider_id == provider_id
        assert connection.credential_id == credential_id
        assert credential.password_ciphertext != _PLAINTEXT.encode("utf-8")


@pytest.mark.asyncio
async def test_plaintext_password_not_stored_at_rest(
    migrated_database: str,
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    _, credential_id, _ = await _commit_provider_aggregate(db_session_factory, cipher)
    conninfo = migrated_database.replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(conninfo, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT password_ciphertext, password_nonce
                FROM credentials
                WHERE id = %s
                """,
                (credential_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            ciphertext, nonce = row
            assert _PLAINTEXT.encode("utf-8") not in ciphertext
            assert _PLAINTEXT.encode("utf-8") not in nonce

    async with db_session_factory() as session:
        result = await session.execute(select(Credential).where(Credential.id == credential_id))
        credential = result.scalar_one()
        assert _PLAINTEXT not in repr(credential)
        assert _PLAINTEXT not in str(credential.password_ciphertext)


@pytest.mark.asyncio
async def test_atomic_rollback_before_commit(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    connection_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(RuntimeError, match="force rollback"):
        async with uow:
            await uow.providers.add_provider(
                AddProviderCommand(provider_id=provider_id, name="rollback-provider")
            )
            await uow.providers.add_credential(
                AddCredentialCommand(
                    credential_id=credential_id,
                    username="service-user",
                    encrypted_password=encrypted,
                    encrypted_username=cipher.encrypt_secret(
                        credential_id=credential_id,
                        field_label="username",
                        plaintext="service-user",
                        key_version=_KEY_VERSION,
                    ),
                )
            )
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=connection_id,
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url="https://keystone.example/v3",
                )
            )
            raise RuntimeError("force rollback")

    async with db_session_factory() as session:
        assert (await session.scalar(select(Provider.id).where(Provider.id == provider_id))) is None
        assert (
            await session.scalar(select(Credential.id).where(Credential.id == credential_id))
        ) is None
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(ProviderConnection.id == connection_id)
            )
        ) is None


@pytest.mark.asyncio
async def test_exit_without_commit_rolls_back(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    connection_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_provider(
            AddProviderCommand(provider_id=provider_id, name="no-commit-provider")
        )
        await uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username="service-user",
                encrypted_password=encrypted,
                encrypted_username=cipher.encrypt_secret(
                    credential_id=credential_id,
                    field_label="username",
                    plaintext="service-user",
                    key_version=_KEY_VERSION,
                ),
            )
        )
        await uow.providers.add_connection(
            AddConnectionCommand(
                connection_id=connection_id,
                provider_id=provider_id,
                credential_id=credential_id,
                project_name="demo",
                region_name="RegionOne",
                auth_url="https://keystone.example/v3",
            )
        )

    async with db_session_factory() as session:
        assert (await session.scalar(select(Provider.id).where(Provider.id == provider_id))) is None


@pytest.mark.asyncio
async def test_second_connection_rollback_leaves_first_committed(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    first_provider_id, first_credential_id, first_connection_id = await _commit_provider_aggregate(
        db_session_factory, cipher
    )
    second_connection_id = new_uuid7()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(RuntimeError, match="force rollback"):
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=second_connection_id,
                    provider_id=first_provider_id,
                    credential_id=first_credential_id,
                    project_name="other-project",
                    region_name="RegionTwo",
                    auth_url="https://keystone.example/v3",
                )
            )
            raise RuntimeError("force rollback")

    async with db_session_factory() as session:
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(ProviderConnection.id == first_connection_id)
            )
        ) == first_connection_id
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(ProviderConnection.id == second_connection_id)
            )
        ) is None


@pytest.mark.asyncio
async def test_duplicate_connection_identity_is_rejected(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, _ = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )
    duplicate_connection_id = new_uuid7()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(DuplicateProviderConnectionError, match="already exists"):
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=duplicate_connection_id,
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url="https://keystone.example/v3",
                )
            )

    async with db_session_factory() as session:
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(
                    ProviderConnection.id == duplicate_connection_id
                )
            )
        ) is None


@pytest.mark.asyncio
async def test_uncommitted_data_not_visible_to_fresh_session(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id = new_uuid7()
    credential_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_provider(
            AddProviderCommand(provider_id=provider_id, name="pending-provider")
        )
        await uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username="service-user",
                encrypted_password=encrypted,
                encrypted_username=cipher.encrypt_secret(
                    credential_id=credential_id,
                    field_label="username",
                    plaintext="service-user",
                    key_version=_KEY_VERSION,
                ),
            )
        )

        async with db_session_factory() as other_session:
            assert (
                await other_session.scalar(select(Provider.id).where(Provider.id == provider_id))
            ) is None


@pytest.mark.asyncio
async def test_persisted_ids_are_uuidv7(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, connection_id = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )

    assert provider_id.version == 7
    assert credential_id.version == 7
    assert connection_id.version == 7


@pytest.mark.asyncio
async def test_duplicate_connection_identity_maps_to_duplicate_error(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, _ = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )
    duplicate_connection_id = new_uuid7()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(DuplicateProviderConnectionError, match="already exists") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=duplicate_connection_id,
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url=_AUTH_URL,
                )
            )

    _assert_redacted_persistence_exception(exc_info.value)

    async with db_session_factory() as session:
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(
                    ProviderConnection.id == duplicate_connection_id
                )
            )
        ) is None


@pytest.mark.asyncio
async def test_duplicate_connection_primary_key_is_not_duplicate_identity(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, connection_id = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=connection_id,
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="other-project",
                    region_name="RegionTwo",
                    auth_url=_AUTH_URL,
                )
            )

    _assert_redacted_persistence_exception(exc_info.value)
    assert not isinstance(exc_info.value, DuplicateProviderConnectionError)

    async with db_session_factory() as session:
        count = await session.scalar(
            select(ProviderConnection.id).where(ProviderConnection.id == connection_id)
        )
        assert count == connection_id


@pytest.mark.asyncio
async def test_invalid_provider_foreign_key_is_not_duplicate_identity(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    _, credential_id, _ = await _commit_provider_aggregate(db_session_factory, cipher)
    missing_provider_id = new_uuid7()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=missing_provider_id,
                    credential_id=credential_id,
                    project_name="demo",
                    region_name="RegionOne",
                    auth_url=_AUTH_URL,
                )
            )

    _assert_redacted_persistence_exception(exc_info.value)
    assert not isinstance(exc_info.value, DuplicateProviderConnectionError)


@pytest.mark.asyncio
async def test_invalid_credential_foreign_key_is_not_duplicate_identity(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, _, _ = await _commit_provider_aggregate(db_session_factory, cipher)
    missing_credential_id = new_uuid7()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=provider_id,
                    credential_id=missing_credential_id,
                    project_name="fk-missing-credential",
                    region_name="RegionFK",
                    auth_url=_AUTH_URL,
                )
            )

    _assert_redacted_persistence_exception(exc_info.value)
    assert not isinstance(exc_info.value, DuplicateProviderConnectionError)


@pytest.mark.asyncio
async def test_invalid_interface_check_is_not_duplicate_identity(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, _ = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="another-demo",
                    region_name="RegionThree",
                    auth_url=_AUTH_URL,
                    interface="bad",
                )
            )

    _assert_redacted_persistence_exception(exc_info.value)
    assert not isinstance(exc_info.value, DuplicateProviderConnectionError)

    async with db_session_factory() as session:
        assert (
            await session.scalar(
                select(ProviderConnection.id).where(
                    ProviderConnection.project_name == "another-demo"
                )
            )
        ) is None


@pytest.mark.asyncio
async def test_provider_data_error_is_sanitized(db_session_factory) -> None:
    provider_id = new_uuid7()
    oversized_name = "provider-sensitive-marker-" + ("x" * 256)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_provider(
                AddProviderCommand(provider_id=provider_id, name=oversized_name)
            )

    _assert_redacted_persistence_exception(
        exc_info.value,
        extra_forbidden=(oversized_name, "StringDataRightTruncation"),
    )
    async with db_session_factory() as session:
        assert (await session.scalar(select(Provider.id).where(Provider.id == provider_id))) is None


@pytest.mark.asyncio
async def test_credential_integrity_error_is_sanitized(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    first_id = new_uuid7()
    duplicate_id = new_uuid7()
    encrypted = cipher.encrypt_password(
        credential_id=first_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    first_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with first_uow:
        await first_uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=first_id,
                username=_USERNAME,
                encrypted_password=encrypted,
                encrypted_username=cipher.encrypt_secret(
                    credential_id=first_id,
                    field_label="username",
                    plaintext=_USERNAME,
                    key_version=_KEY_VERSION,
                ),
            )
        )
        await first_uow.commit()

    duplicate_uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with duplicate_uow:
            await duplicate_uow.providers.add_credential(
                AddCredentialCommand(
                    credential_id=duplicate_id,
                    username=_USERNAME,
                    encrypted_password=encrypted,
                    encrypted_username=cipher.encrypt_secret(
                        credential_id=duplicate_id,
                        field_label="username",
                        plaintext=_USERNAME,
                        key_version=_KEY_VERSION,
                    ),
                )
            )

    _assert_redacted_persistence_exception(
        exc_info.value,
        extra_forbidden=(encrypted.ciphertext.hex(), encrypted.nonce.hex(), _KEY_VERSION),
    )
    async with db_session_factory() as session:
        assert (
            await session.scalar(select(Credential.id).where(Credential.id == duplicate_id))
        ) is None


@pytest.mark.asyncio
async def test_credential_username_is_not_persisted_as_plaintext(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    credential_id = new_uuid7()
    oversized_username = "credential-sensitive-marker-" + ("x" * 256)
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )

    encrypted_username = cipher.encrypt_secret(
        credential_id=credential_id,
        field_label="username",
        plaintext=oversized_username,
        key_version=_KEY_VERSION,
    )
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.providers.add_credential(
            AddCredentialCommand(
                credential_id=credential_id,
                username=oversized_username,
                encrypted_username=encrypted_username,
                encrypted_password=encrypted,
            )
        )
        await uow.commit()
    async with db_session_factory() as session:
        row = await session.get(Credential, credential_id)
        assert row is not None
        assert not hasattr(row, "username")
        assert oversized_username.encode() not in row.username_ciphertext


@pytest.mark.asyncio
async def test_connection_data_error_is_sanitized(
    db_session_factory,
    cipher: AesGcmCredentialCipher,
) -> None:
    provider_id, credential_id, _ = await _commit_provider_aggregate(
        db_session_factory,
        cipher,
    )
    oversized_interface = "sensitive-interface-marker"

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ProviderPersistenceError, match="provider persistence failed") as exc_info:
        async with uow:
            await uow.providers.add_connection(
                AddConnectionCommand(
                    connection_id=new_uuid7(),
                    provider_id=provider_id,
                    credential_id=credential_id,
                    project_name="data-error-project",
                    region_name="RegionDataError",
                    auth_url=_AUTH_URL,
                    interface=oversized_interface,
                )
            )

    _assert_redacted_persistence_exception(
        exc_info.value,
        extra_forbidden=(oversized_interface, "StringDataRightTruncation"),
    )
