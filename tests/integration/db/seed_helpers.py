"""Shared seed helpers for schema negative integration tests."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from cps.identifiers import new_uuid7

VALID_NONCE = bytes.fromhex("000000000000000000000000")


def insert_provider(
    conn: psycopg.Connection,
    *,
    provider_id: uuid.UUID | None = None,
    version: int = 1,
) -> uuid.UUID:
    provider_id = provider_id or uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO providers (id, name, provider_type, status, version)
            VALUES (%s, %s, 'OPENSTACK', 'ACTIVE', %s)
            """,
            (provider_id, f"provider-{provider_id.hex[:8]}", version),
        )
    return provider_id


def insert_credential(
    conn: psycopg.Connection,
    *,
    credential_id: uuid.UUID | None = None,
    nonce: bytes = VALID_NONCE,
    key_version: str = "v1",
    version: int = 1,
) -> uuid.UUID:
    credential_id = credential_id or uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO credentials (
                id, username_ciphertext, username_nonce, password_ciphertext, password_nonce,
                encryption_key_version, version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (credential_id, b"user-cipher", nonce, b"\x00", nonce, key_version, version),
        )
    return credential_id


def insert_connection(
    conn: psycopg.Connection,
    *,
    provider_id: uuid.UUID,
    credential_id: uuid.UUID,
    connection_id: uuid.UUID | None = None,
    project_domain_name: str = "Default",
    project_name: str = "demo",
    region_name: str = "RegionOne",
    interface: str = "public",
    version: int = 1,
) -> uuid.UUID:
    connection_id = connection_id or uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO provider_connections (
                id, provider_id, credential_id, project_name, project_domain_name,
                region_name, auth_url, interface, verify_tls, status, version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                'https://keystone.example/v3', %s, true, 'PENDING_VALIDATION', %s
            )
            """,
            (
                connection_id,
                provider_id,
                credential_id,
                project_name,
                project_domain_name,
                region_name,
                interface,
                version,
            ),
        )
    return connection_id


def insert_operation(
    conn: psycopg.Connection,
    *,
    connection_id: uuid.UUID,
    operation_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    progress_percent: int | None = None,
    version: int = 1,
    state: str = "ACCEPTED",
) -> uuid.UUID:
    operation_id = operation_id or uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operations (
                id, provider_connection_id, operation_type, state,
                progress_percent, idempotency_key, request_fingerprint,
                request_payload, correlation_id, version
            )
            VALUES (
                %s, %s, 'openstack.connection.validate', %s,
                %s, %s, %s, '{}'::jsonb, %s, %s
            )
            """,
            (
                operation_id,
                connection_id,
                state,
                progress_percent,
                idempotency_key,
                "a" * 64,
                uuid.uuid4(),
                version,
            ),
        )
    return operation_id


def seed_operation_graph(conn: psycopg.Connection) -> dict[str, uuid.UUID]:
    provider_id = insert_provider(conn)
    credential_id = insert_credential(conn, nonce=new_uuid7().bytes[:12])
    connection_id = insert_connection(conn, provider_id=provider_id, credential_id=credential_id)
    operation_id = insert_operation(conn, connection_id=connection_id)
    return {
        "provider_id": provider_id,
        "credential_id": credential_id,
        "connection_id": connection_id,
        "operation_id": operation_id,
    }


def assert_integrity_error(conn: psycopg.Connection, sql: str, params: tuple[Any, ...]) -> None:
    import pytest

    with conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.IntegrityError):
            cursor.execute(sql, params)
