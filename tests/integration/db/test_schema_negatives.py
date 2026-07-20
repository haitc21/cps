"""CPS-103 Task 2: PostgreSQL negative constraint integration tests."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.db.seed_helpers import (
    VALID_NONCE,
    assert_integrity_error,
    insert_connection,
    insert_credential,
    insert_operation,
    insert_provider,
    seed_operation_graph,
)

pytestmark = pytest.mark.integration


def test_credential_nonce_too_short(db_tx: psycopg.Connection) -> None:
    short_nonce = bytes.fromhex("000000000000")
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO credentials (
            id, username, password_ciphertext, password_nonce,
            encryption_key_version, version
        )
        VALUES (%s, 'user1', %s, %s, 'v1', 1)
        """,
        (uuid.uuid4(), b"\x00", short_nonce),
    )


def test_duplicate_credential_encryption_nonce(db_tx: psycopg.Connection) -> None:
    insert_credential(db_tx, key_version="v1", nonce=VALID_NONCE)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO credentials (
            id, username, password_ciphertext, password_nonce,
            encryption_key_version, version
        )
        VALUES (%s, 'user2', %s, %s, 'v1', 1)
        """,
        (uuid.uuid4(), b"\x01", VALID_NONCE),
    )


def test_duplicate_provider_connection_identity(db_tx: psycopg.Connection) -> None:
    provider_id = insert_provider(db_tx)
    credential_id = insert_credential(db_tx)
    insert_connection(db_tx, provider_id=provider_id, credential_id=credential_id)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO provider_connections (
            id, provider_id, credential_id, project_name, project_domain_name,
            region_name, auth_url, interface, verify_tls, status, version
        )
        VALUES (
            %s, %s, %s, 'demo', 'Default', 'RegionOne',
            'https://keystone.example/v3', 'public', true, 'PENDING_VALIDATION', 1
        )
        """,
        (uuid.uuid4(), provider_id, credential_id),
    )


def test_different_domain_same_project_region_allowed(db_tx: psycopg.Connection) -> None:
    provider_id = insert_provider(db_tx)
    credential_id = insert_credential(db_tx)
    insert_connection(
        db_tx,
        provider_id=provider_id,
        credential_id=credential_id,
        project_domain_name="Default",
    )
    insert_connection(
        db_tx,
        provider_id=provider_id,
        credential_id=credential_id,
        project_domain_name="OtherDomain",
        connection_id=uuid.uuid4(),
    )


def test_invalid_provider_type(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO providers (id, name, provider_type, status, version)
        VALUES (%s, 'bad-provider', 'AWS', 'ACTIVE', 1)
        """,
        (uuid.uuid4(),),
    )


def test_invalid_connection_interface(db_tx: psycopg.Connection) -> None:
    provider_id = insert_provider(db_tx)
    credential_id = insert_credential(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO provider_connections (
            id, provider_id, credential_id, project_name, project_domain_name,
            region_name, auth_url, interface, verify_tls, status, version
        )
        VALUES (
            %s, %s, %s, 'demo', 'Default', 'RegionOne',
            'https://keystone.example/v3', 'invalid', true, 'PENDING_VALIDATION', 1
        )
        """,
        (uuid.uuid4(), provider_id, credential_id),
    )


def test_operation_progress_negative(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO operations (
            id, provider_connection_id, operation_type, state,
            progress_percent, request_fingerprint, request_payload,
            correlation_id, version
        )
        VALUES (%s, %s, 'openstack.connection.validate', 'ACCEPTED', -1, %s, '{}'::jsonb, %s, 1)
        """,
        (uuid.uuid4(), ids["connection_id"], "a" * 64, uuid.uuid4()),
    )


def test_operation_progress_over_100(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO operations (
            id, provider_connection_id, operation_type, state,
            progress_percent, request_fingerprint, request_payload,
            correlation_id, version
        )
        VALUES (%s, %s, 'openstack.connection.validate', 'ACCEPTED', 101, %s, '{}'::jsonb, %s, 1)
        """,
        (uuid.uuid4(), ids["connection_id"], "a" * 64, uuid.uuid4()),
    )


def test_provider_version_zero(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO providers (id, name, provider_type, status, version)
        VALUES (%s, 'v0-provider', 'OPENSTACK', 'ACTIVE', 0)
        """,
        (uuid.uuid4(),),
    )


def test_credential_version_zero(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO credentials (
            id, username, password_ciphertext, password_nonce,
            encryption_key_version, version
        )
        VALUES (%s, 'user1', %s, %s, 'v1', 0)
        """,
        (uuid.uuid4(), b"\x00", VALID_NONCE),
    )


def test_provider_connection_version_zero(db_tx: psycopg.Connection) -> None:
    provider_id = insert_provider(db_tx)
    credential_id = insert_credential(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO provider_connections (
            id, provider_id, credential_id, project_name, project_domain_name,
            region_name, auth_url, interface, verify_tls, status, version
        )
        VALUES (
            %s, %s, %s, 'demo', 'Default', 'RegionOne',
            'https://keystone.example/v3', 'public', true, 'PENDING_VALIDATION', 0
        )
        """,
        (uuid.uuid4(), provider_id, credential_id),
    )


def test_operation_version_zero(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO operations (
            id, provider_connection_id, operation_type, state,
            request_fingerprint, request_payload, correlation_id, version
        )
        VALUES (%s, %s, 'openstack.connection.validate', 'ACCEPTED', %s, '{}'::jsonb, %s, 0)
        """,
        (uuid.uuid4(), ids["connection_id"], "a" * 64, uuid.uuid4()),
    )


def test_outbox_version_zero(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'PENDING', 0, 0
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_operation_event_sequence_zero(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO operation_events (
            id, operation_id, sequence, event_type, details
        )
        VALUES (%s, %s, 0, 'STATE_CHANGED', '{}'::jsonb)
        """,
        (uuid.uuid4(), ids["operation_id"]),
    )


def test_outbox_attempt_count_negative(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'PENDING', -1, 1
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_outbox_claimed_missing_claimed_by(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version,
            claim_token, claim_expires_at
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'CLAIMED', 0, 1,
            %s, NOW()
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_outbox_claimed_missing_claim_token(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version,
            claimed_by, claim_expires_at
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'CLAIMED', 0, 1,
            'worker-1', NOW()
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_outbox_claimed_missing_claim_expires_at(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version,
            claimed_by, claim_token
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'CLAIMED', 0, 1,
            'worker-1', %s
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_outbox_pending_with_claim_fields(db_tx: psycopg.Connection) -> None:
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO outbox_messages (
            id, aggregate_type, aggregate_id, message_id, message_type,
            routing_key, payload, publish_state, attempt_count, version,
            claimed_by
        )
        VALUES (
            %s, 'operation', %s, %s, 'OperationCreated',
            'cps.operation.created', '{}'::jsonb, 'PENDING', 0, 1,
            'worker-1'
        )
        """,
        (uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
    )


def test_duplicate_non_null_idempotency_scope(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    insert_operation(
        db_tx,
        connection_id=ids["connection_id"],
        idempotency_key="idem-1",
    )
    assert_integrity_error(
        db_tx,
        """
        INSERT INTO operations (
            id, provider_connection_id, operation_type, state,
            idempotency_key, request_fingerprint, request_payload,
            correlation_id, version
        )
        VALUES (
            %s, %s, 'openstack.connection.validate', 'ACCEPTED',
            'idem-1', %s, '{}'::jsonb, %s, 1
        )
        """,
        (uuid.uuid4(), ids["connection_id"], "b" * 64, uuid.uuid4()),
    )


def test_null_idempotency_keys_do_not_collide(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    insert_operation(db_tx, connection_id=ids["connection_id"], idempotency_key=None)
    insert_operation(
        db_tx,
        connection_id=ids["connection_id"],
        operation_id=uuid.uuid4(),
        idempotency_key=None,
    )


def test_delete_provider_with_dependent_restricted(db_tx: psycopg.Connection) -> None:
    provider_id = insert_provider(db_tx)
    credential_id = insert_credential(db_tx)
    insert_connection(db_tx, provider_id=provider_id, credential_id=credential_id)
    assert_integrity_error(
        db_tx,
        "DELETE FROM providers WHERE id = %s",
        (provider_id,),
    )


def test_delete_connection_with_operation_restricted(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    assert_integrity_error(
        db_tx,
        "DELETE FROM provider_connections WHERE id = %s",
        (ids["connection_id"],),
    )


def test_delete_operation_does_not_cascade_events(db_tx: psycopg.Connection) -> None:
    ids = seed_operation_graph(db_tx)
    with db_tx.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operation_events (
                id, operation_id, sequence, event_type, details
            )
            VALUES (%s, %s, 1, 'STATE_CHANGED', '{}'::jsonb)
            """,
            (uuid.uuid4(), ids["operation_id"]),
        )
    assert_integrity_error(
        db_tx,
        "DELETE FROM operations WHERE id = %s",
        (ids["operation_id"],),
    )
