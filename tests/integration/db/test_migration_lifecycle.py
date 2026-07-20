"""CPS-103 Task 2: Alembic migration lifecycle integration tests."""

from __future__ import annotations

import psycopg
import pytest

from tests.integration.db.conftest import (
    CORE_TABLES,
    ENUM_TYPES,
    list_public_enum_types,
    list_public_tables,
    run_alembic,
)

pytestmark = pytest.mark.integration


def test_upgrade_from_base_creates_exact_core_tables(
    fresh_migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    tables = list_public_tables(db_admin_conn)
    allowed = CORE_TABLES | {"alembic_version"}
    assert tables == allowed


def test_downgrade_drops_core_tables(
    fresh_migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    run_alembic(fresh_migrated_database, "base")
    tables = list_public_tables(db_admin_conn)
    assert CORE_TABLES.isdisjoint(tables)


def test_downgrade_drops_enum_types(
    fresh_migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    run_alembic(fresh_migrated_database, "base")
    enums = list_public_enum_types(db_admin_conn)
    assert set(ENUM_TYPES).isdisjoint(enums)


def test_reupgrade_succeeds_and_leaves_head(
    fresh_migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    run_alembic(fresh_migrated_database, "base")
    run_alembic(fresh_migrated_database, "head")
    tables = list_public_tables(db_admin_conn)
    assert tables == CORE_TABLES | {"alembic_version"}


def test_empty_to_head_does_not_duplicate_enums(
    fresh_migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    enums = list_public_enum_types(db_admin_conn)
    assert enums == set(ENUM_TYPES)


def test_operation_events_reuses_operation_state_enum(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    with db_admin_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'operation_events'
              AND column_name IN ('from_state', 'to_state')
            ORDER BY column_name
            """
        )
        rows = cursor.fetchall()
    assert [row[0] for row in rows] == ["operation_state", "operation_state"]
