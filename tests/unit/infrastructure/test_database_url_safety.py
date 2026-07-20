"""Unit tests for integration test database URL safety."""

from __future__ import annotations

import pytest
from psycopg import sql

from tests.integration.db.database_url import (
    ALLOWED_TEST_DATABASE,
    DatabaseUrlValidationError,
    parse_database_name,
    require_test_database_url,
    validate_test_database_url,
)
from tests.integration.db.disposable_database import DisposableDatabaseManager

_TEST_HOST = "127.0.0.1:5432"


def _test_url(database_name: str) -> str:
    return f"postgresql+psycopg://cps@{_TEST_HOST}/{database_name}"


def test_parse_database_name_extracts_cps_test() -> None:
    assert parse_database_name(_test_url(ALLOWED_TEST_DATABASE)) == ALLOWED_TEST_DATABASE


def test_validate_rejects_dev_database_cps() -> None:
    with pytest.raises(DatabaseUrlValidationError, match="forbidden database 'cps'"):
        validate_test_database_url(_test_url("cps"))


def test_validate_rejects_postgres_database() -> None:
    with pytest.raises(DatabaseUrlValidationError, match="forbidden database 'postgres'"):
        validate_test_database_url(_test_url("postgres"))


def test_validate_rejects_arbitrary_database_name() -> None:
    with pytest.raises(DatabaseUrlValidationError, match="must use database 'cps_test'"):
        validate_test_database_url(_test_url("other_db"))


def test_validate_accepts_cps_test() -> None:
    validate_test_database_url(_test_url(ALLOWED_TEST_DATABASE))


def test_validate_rejects_missing_database_name() -> None:
    url = f"postgresql+psycopg://cps@{_TEST_HOST}/"
    with pytest.raises(DatabaseUrlValidationError, match="must include a database name"):
        validate_test_database_url(url)


def test_require_test_database_url_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPS_RUN_INTEGRATION", "1")
    monkeypatch.delenv("CPS_TEST_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseUrlValidationError, match="CPS_TEST_DATABASE_URL is required"):
        require_test_database_url()


def test_create_database_uses_identifier_not_string_interpolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    class FakeCursor:
        def execute(self, query: object, params: object = None) -> None:
            captured.append((query, params))

        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def fetchone(self) -> None:
            return None

    class FakeConnection:
        autocommit = True

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("psycopg.connect", lambda *_args, **_kwargs: FakeConnection())
    manager = DisposableDatabaseManager(_test_url(ALLOWED_TEST_DATABASE))
    manager.create_session_database(worker_id="gw0", suffix="abc123")

    create_query, create_params = captured[1]
    assert create_params is None
    assert isinstance(create_query, sql.Composed)
    assert "CREATE DATABASE" in create_query.as_string(None)
