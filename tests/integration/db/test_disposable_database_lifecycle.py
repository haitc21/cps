"""Integration tests for disposable database fixture lifecycle."""

from __future__ import annotations

import secrets

import psycopg
import pytest

from tests.integration.db.conftest import (
    TemplateSchemaSnapshot,
    capture_template_schema,
    list_public_tables,
    run_alembic,
)
from tests.integration.db.database_url import admin_conninfo
from tests.integration.db.disposable_database import (
    DisposableDatabaseManager,
    is_disposable_database_name,
)

pytestmark = pytest.mark.integration


def test_template_database_is_never_migrated(
    template_database_conn: psycopg.Connection,
    template_schema_snapshot: TemplateSchemaSnapshot,
    migrated_database: str,
) -> None:
    del migrated_database
    with template_database_conn.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        current_database = cursor.fetchone()
    assert current_database == ("cps_test",)
    assert template_schema_snapshot == capture_template_schema(template_database_conn)


def test_session_uses_disposable_database_name(integration_database_url: str) -> None:
    database_name = integration_database_url.rsplit("/", maxsplit=1)[-1]
    assert is_disposable_database_name(database_name)


def test_disposable_database_receives_migrations(integration_database_url: str) -> None:
    conninfo = integration_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        tables = list_public_tables(connection)
    assert "alembic_version" in tables


def test_fixture_cleanup_drops_disposable_database(
    integration_template_database_url: str,
) -> None:
    manager = DisposableDatabaseManager(integration_template_database_url)
    suffix = secrets.token_hex(8)
    database_url = manager.create_session_database(worker_id="gw0", suffix=suffix)
    database_name = database_url.rsplit("/", maxsplit=1)[-1]
    admin = admin_conninfo(integration_template_database_url)

    with psycopg.connect(admin, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            assert cursor.fetchone() is not None

    manager.cleanup()

    with psycopg.connect(admin, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            assert cursor.fetchone() is None


def test_run_alembic_rejects_template_in_integration(
    integration_template_database_url: str,
) -> None:
    with pytest.raises(Exception, match="must not run against template database"):
        run_alembic(integration_template_database_url, "head")


def test_concurrent_workers_use_distinct_databases(
    integration_template_database_url: str,
) -> None:
    first = DisposableDatabaseManager(integration_template_database_url)
    second = DisposableDatabaseManager(integration_template_database_url)
    first_url = first.create_session_database(worker_id="gw0", suffix=secrets.token_hex(8))
    second_url = second.create_session_database(worker_id="gw1", suffix=secrets.token_hex(8))

    assert first_url != second_url

    first.cleanup()
    second.cleanup()


def test_fixture_cleanup_runs_after_failure(
    integration_template_database_url: str,
) -> None:
    manager = DisposableDatabaseManager(integration_template_database_url)
    database_url = manager.create_session_database(worker_id="gw0", suffix=secrets.token_hex(8))
    database_name = database_url.rsplit("/", maxsplit=1)[-1]
    admin = admin_conninfo(integration_template_database_url)
    failed = False

    try:
        msg = "forced integration failure"
        raise RuntimeError(msg)
    except RuntimeError:
        failed = True
    finally:
        manager.cleanup()

    assert failed
    with psycopg.connect(admin, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            assert cursor.fetchone() is None
