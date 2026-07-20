"""Integration fixtures for PostgreSQL persistence tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cps.config import clear_settings_cache
from cps.infrastructure.db.engine import create_database_engine
from cps.infrastructure.db.session import create_session_factory
from cps.infrastructure.db.urls import to_psycopg_conninfo
from tests.integration.db.database_url import validate_test_database_url
from tests.integration.db.disposable_database import (
    DisposableDatabaseManager,
    read_worker_id,
    reject_template_for_migrations,
)

pytestmark = pytest.mark.integration

CORE_TABLES = frozenset(
    {
        "providers",
        "credentials",
        "provider_connections",
        "operations",
        "operation_events",
        "outbox_messages",
        "inbox_messages",
    }
)

ENUM_TYPES = (
    "provider_status",
    "connection_status",
    "operation_state",
    "outbox_publish_state",
    "inbox_process_state",
)

type TemplateSchemaSnapshot = tuple[frozenset[str], frozenset[str], tuple[str, ...]]


def run_alembic(database_url: str, revision: str) -> None:
    reject_template_for_migrations(database_url)
    os.environ["CPS_DATABASE_URL"] = database_url
    os.environ["CPS_ENVIRONMENT"] = "test"
    clear_settings_cache()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    if revision == "head":
        command.upgrade(config, "head")
    else:
        command.downgrade(config, revision)


@pytest.fixture(scope="session")
def integration_template_database_url() -> str:
    if os.getenv("CPS_RUN_INTEGRATION", "0") != "1":
        pytest.skip("integration disabled; set CPS_RUN_INTEGRATION=1")
    template_url = os.getenv("CPS_TEST_DATABASE_URL")
    if not template_url:
        pytest.fail("CPS_TEST_DATABASE_URL is required when CPS_RUN_INTEGRATION=1")
    validate_test_database_url(template_url)
    return template_url


@pytest.fixture(scope="session")
def disposable_database_manager(
    integration_template_database_url: str,
    template_schema_snapshot: TemplateSchemaSnapshot,
) -> Iterator[DisposableDatabaseManager]:
    del template_schema_snapshot
    manager = DisposableDatabaseManager(integration_template_database_url)
    manager.create_session_database(worker_id=read_worker_id())
    try:
        yield manager
    finally:
        manager.cleanup()


@pytest.fixture(scope="session")
def template_database_conn(
    integration_template_database_url: str,
) -> Iterator[psycopg.Connection]:
    conninfo = to_psycopg_conninfo(integration_template_database_url)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        yield connection


@pytest.fixture(scope="session")
def template_schema_snapshot(
    template_database_conn: psycopg.Connection,
) -> TemplateSchemaSnapshot:
    return capture_template_schema(template_database_conn)


@pytest.fixture(scope="session")
def integration_database_url(disposable_database_manager: DisposableDatabaseManager) -> str:
    assert disposable_database_manager.database_url is not None
    return disposable_database_manager.database_url


@pytest.fixture(scope="session")
def migrated_database(integration_database_url: str) -> Iterator[str]:
    run_alembic(integration_database_url, "head")
    yield integration_database_url


@pytest.fixture
def fresh_migrated_database(integration_database_url: str) -> Iterator[str]:
    run_alembic(integration_database_url, "base")
    run_alembic(integration_database_url, "head")
    yield integration_database_url


@pytest.fixture(scope="session")
def db_admin_conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    conninfo = to_psycopg_conninfo(migrated_database)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        yield connection


@pytest.fixture
def db_tx(migrated_database: str) -> Iterator[psycopg.Connection]:
    conninfo = to_psycopg_conninfo(migrated_database)
    connection = psycopg.connect(conninfo, autocommit=False)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
async def db_engine(fresh_migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_database_engine(fresh_migrated_database)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


def list_public_tables(connection: psycopg.Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = 'public'
            """
        )
        rows = cursor.fetchall()
    return {row[0] for row in rows}


def list_public_enum_types(connection: psycopg.Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.typname
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public' AND t.typtype = 'e'
            """
        )
        rows = cursor.fetchall()
    return {row[0] for row in rows}


def constraint_names(connection: psycopg.Connection, table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = 'public' AND t.relname = %s
            """,
            (table,),
        )
        rows = cursor.fetchall()
    return {row[0] for row in rows}


def foreign_keys(connection: psycopg.Connection, table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND t.relname = %s
              AND c.contype = 'f'
            ORDER BY c.conname
            """,
            (table,),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def index_definitions(connection: psycopg.Connection, table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = %s
            ORDER BY indexname
            """,
            (table,),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def check_constraints(connection: psycopg.Connection, table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND t.relname = %s
              AND c.contype = 'c'
            ORDER BY c.conname
            """,
            (table,),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def column_nullable(connection: psycopg.Connection, table: str, column: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            """,
            (table, column),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0] == "YES"


def column_data_type(connection: psycopg.Connection, table: str, column: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            """,
            (table, column),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def table_columns(connection: psycopg.Connection, table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table,),
        )
        rows = cursor.fetchall()
    return {row[0] for row in rows}


def enum_labels(connection: psycopg.Connection, enum_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.enumlabel
            FROM pg_catalog.pg_enum e
            JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
            JOIN pg_catalog.pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public' AND t.typname = %s
            ORDER BY e.enumsortorder
            """,
            (enum_name,),
        )
        rows = cursor.fetchall()
    return [row[0] for row in rows]


def uuid_pk_has_default(connection: psycopg.Connection, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_default IS NOT NULL
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = 'id'
            """,
            (table,),
        )
        row = cursor.fetchone()
    assert row is not None
    return bool(row[0])


def capture_template_schema(connection: psycopg.Connection) -> TemplateSchemaSnapshot:
    tables = frozenset(list_public_tables(connection))
    enums = frozenset(list_public_enum_types(connection))
    alembic_rows: tuple[str, ...] = ()
    if "alembic_version" in tables:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
            alembic_rows = tuple(row[0] for row in cursor.fetchall())
    return tables, enums, alembic_rows
