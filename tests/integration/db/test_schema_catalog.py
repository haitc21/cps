"""CPS-103 Task 2: PostgreSQL catalog introspection tests."""

from __future__ import annotations

import psycopg
import pytest

from tests.integration.db.conftest import (
    check_constraints,
    column_data_type,
    column_nullable,
    constraint_names,
    enum_labels,
    foreign_keys,
    index_definitions,
    table_columns,
    uuid_pk_has_default,
)

pytestmark = pytest.mark.integration

PRIMARY_KEYS = {
    "credentials": "pk_credentials",
    "inbox_messages": "pk_inbox_messages",
    "outbox_messages": "pk_outbox_messages",
    "providers": "pk_providers",
    "provider_connections": "pk_provider_connections",
    "operations": "pk_operations",
    "operation_events": "pk_operation_events",
}

FOREIGN_KEYS = {
    "provider_connections": {
        "fk_provider_connections_credential_id_credentials": (
            "FOREIGN KEY (credential_id) REFERENCES credentials(id) ON DELETE RESTRICT"
        ),
        "fk_provider_connections_provider_id_providers": (
            "FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE RESTRICT"
        ),
    },
    "operations": {
        "fk_operations_provider_connection_id_provider_connections": (
            "FOREIGN KEY (provider_connection_id) REFERENCES provider_connections(id) "
            "ON DELETE RESTRICT"
        ),
    },
    "operation_events": {
        "fk_operation_events_operation_id_operations": (
            "FOREIGN KEY (operation_id) REFERENCES operations(id) ON DELETE RESTRICT"
        ),
    },
}

UNIQUE_CONSTRAINTS = {
    "credentials": {"uq_credentials_encryption_key_version_password_nonce"},
    "inbox_messages": {"uq_inbox_messages_consumer_message"},
    "outbox_messages": {"uq_outbox_messages_message_id"},
    "provider_connections": {"uq_provider_connections_provider_domain_project_region"},
    "operation_events": {"uq_operation_events_operation_sequence"},
}

NORMAL_INDEXES = {
    "inbox_messages": {"ix_inbox_messages_process_state"},
    "providers": {"ix_providers_name", "ix_providers_status"},
    "provider_connections": {
        "ix_provider_connections_provider_id",
        "ix_provider_connections_status",
    },
    "operations": {
        "ix_operations_correlation_id",
        "ix_operations_created_at",
        "ix_operations_provider_connection_id",
        "ix_operations_state",
    },
    "operation_events": {"ix_operation_events_operation_id"},
}

CHECKS = {
    "providers": {
        "ck_providers_provider_type_openstack",
        "ck_providers_version_positive",
    },
    "credentials": {
        "ck_credentials_password_nonce_length",
        "ck_credentials_version_positive",
    },
    "provider_connections": {
        "ck_provider_connections_interface_allowed",
        "ck_provider_connections_version_positive",
    },
    "operations": {
        "ck_operations_progress_percent_range",
        "ck_operations_version_positive",
    },
    "operation_events": {"ck_operation_events_sequence_positive"},
    "outbox_messages": {
        "ck_outbox_messages_claim_fields",
        "ck_outbox_messages_attempt_count_nonnegative",
        "ck_outbox_messages_version_positive",
    },
}

ENUMS = {
    "provider_status": ["ACTIVE", "DISABLED"],
    "connection_status": ["PENDING_VALIDATION", "VALID", "INVALID", "DISABLED"],
    "operation_state": [
        "ACCEPTED",
        "QUEUED",
        "RUNNING",
        "WAITING_PROVIDER",
        "SUCCEEDED",
        "FAILED",
        "TIMED_OUT",
    ],
    "outbox_publish_state": ["PENDING", "CLAIMED", "PUBLISHED", "FAILED"],
    "inbox_process_state": ["RECEIVED", "PROCESSED"],
}

TIMESTAMPTZ_COLUMNS = {
    "provider_connections": {"validated_at"},
    "operations": {"timeout_at", "created_at", "updated_at"},
    "operation_events": {"occurred_at"},
    "outbox_messages": {"next_attempt_at", "claim_expires_at", "published_at", "created_at"},
    "inbox_messages": {"received_at", "processed_at"},
}


@pytest.mark.parametrize("table,pk_name", list(PRIMARY_KEYS.items()))
def test_primary_key_name(
    migrated_database: str, db_admin_conn: psycopg.Connection, table: str, pk_name: str
) -> None:
    names = constraint_names(db_admin_conn, table)
    assert pk_name in names


@pytest.mark.parametrize("table,expected", list(FOREIGN_KEYS.items()))
def test_foreign_key_names_and_on_delete(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
    expected: dict[str, str],
) -> None:
    fks = foreign_keys(db_admin_conn, table)
    assert set(fks) == set(expected)
    for name, definition in expected.items():
        assert fks[name] == definition


@pytest.mark.parametrize("table,expected", list(UNIQUE_CONSTRAINTS.items()))
def test_unique_constraint_names(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
    expected: set[str],
) -> None:
    names = constraint_names(db_admin_conn, table)
    assert expected.issubset(names)


@pytest.mark.parametrize("table,expected", list(NORMAL_INDEXES.items()))
def test_normal_index_names(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
    expected: set[str],
) -> None:
    indexes = index_definitions(db_admin_conn, table)
    assert expected.issubset(set(indexes))


def test_operations_idempotency_partial_unique_index(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    indexes = index_definitions(db_admin_conn, "operations")
    assert "uq_operations_idempotency" in indexes
    definition = indexes["uq_operations_idempotency"]
    assert "UNIQUE INDEX" in definition
    assert "idempotency_key IS NOT NULL" in definition


def test_outbox_partial_indexes(migrated_database: str, db_admin_conn: psycopg.Connection) -> None:
    indexes = index_definitions(db_admin_conn, "outbox_messages")
    pending = indexes["ix_outbox_messages_publish_pending"]
    claim = indexes["ix_outbox_messages_claim_expiry"]
    assert "publish_state = 'PENDING'" in pending
    assert "publish_state = 'CLAIMED'" in claim


@pytest.mark.parametrize("table,expected", list(CHECKS.items()))
def test_check_constraint_names(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
    expected: set[str],
) -> None:
    checks = check_constraints(db_admin_conn, table)
    assert expected == set(checks)


def test_operations_provider_connection_not_null(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    assert column_nullable(db_admin_conn, "operations", "provider_connection_id") is False


def test_operations_has_no_provider_id(
    migrated_database: str, db_admin_conn: psycopg.Connection
) -> None:
    columns = table_columns(db_admin_conn, "operations")
    assert "provider_id" not in columns


@pytest.mark.parametrize("enum_name,labels", list(ENUMS.items()))
def test_enum_names_and_values(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    enum_name: str,
    labels: list[str],
) -> None:
    assert enum_labels(db_admin_conn, enum_name) == labels
    assert "CANCELLED" not in enum_labels(db_admin_conn, enum_name)


@pytest.mark.parametrize(
    "table",
    [
        "providers",
        "credentials",
        "provider_connections",
        "operations",
        "operation_events",
        "outbox_messages",
        "inbox_messages",
    ],
)
def test_uuid_primary_keys_have_no_db_default(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
) -> None:
    assert uuid_pk_has_default(db_admin_conn, table) is False


def test_credentials_has_no_plaintext_password_column(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    columns = table_columns(db_admin_conn, "credentials")
    assert "password" not in columns
    assert "password_ciphertext" in columns


def test_outbox_has_no_updated_at(
    migrated_database: str, db_admin_conn: psycopg.Connection
) -> None:
    columns = table_columns(db_admin_conn, "outbox_messages")
    assert "updated_at" not in columns
    assert "created_at" in columns


@pytest.mark.parametrize("table,columns", list(TIMESTAMPTZ_COLUMNS.items()))
def test_timestamptz_catalog_types(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
    table: str,
    columns: set[str],
) -> None:
    for column in columns:
        assert column_data_type(db_admin_conn, table, column) == "timestamp with time zone"
