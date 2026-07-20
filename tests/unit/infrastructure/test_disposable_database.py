"""Unit tests for disposable integration database lifecycle."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

from tests.integration.db.conftest import run_alembic
from tests.integration.db.database_url import ALLOWED_TEST_DATABASE
from tests.integration.db.disposable_database import (
    DisposableDatabaseError,
    DisposableDatabaseManager,
    build_database_url,
    generate_database_name,
    is_disposable_database_name,
    reject_template_for_migrations,
    sanitize_name_part,
)

_TEST_HOST = "127.0.0.1:5432"


def _template_url() -> str:
    return f"postgresql+psycopg://cps@{_TEST_HOST}/{ALLOWED_TEST_DATABASE}"


_DISPOSABLE_CONNECT = "tests.integration.db.disposable_database.psycopg.connect"


def _patch_connect(monkeypatch: pytest.MonkeyPatch, connection: object) -> None:
    monkeypatch.setattr(_DISPOSABLE_CONNECT, lambda *_a, **_k: connection)


def _disposable_url(database_name: str) -> str:
    return build_database_url(_template_url(), database_name)


def test_run_alembic_rejects_template_database() -> None:
    with pytest.raises(DisposableDatabaseError, match="must not run against template database"):
        run_alembic(_template_url(), "head")


def test_generate_database_name_includes_worker_and_suffix() -> None:
    name = generate_database_name(worker_id="gw0", suffix="abc123")
    assert name == "cps_test_gw0_abc123"


def test_two_generated_names_differ_for_different_workers() -> None:
    first = generate_database_name(worker_id="gw0", suffix="same")
    second = generate_database_name(worker_id="gw1", suffix="same")
    assert first != second


def test_two_generated_names_differ_for_different_suffixes() -> None:
    first = generate_database_name(worker_id="master", suffix="aaa")
    second = generate_database_name(worker_id="master", suffix="bbb")
    assert first != second


def test_sanitize_rejects_empty_after_sanitization() -> None:
    with pytest.raises(DisposableDatabaseError, match="invalid disposable database name part"):
        sanitize_name_part("!!!")


def test_sanitize_normalizes_mixed_case_and_symbols() -> None:
    assert sanitize_name_part("GW-0") == "gw0"


def test_disposable_name_rejects_template_exact_name() -> None:
    assert is_disposable_database_name(ALLOWED_TEST_DATABASE) is False


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

    _patch_connect(monkeypatch, FakeConnection())
    manager = DisposableDatabaseManager(_template_url())
    manager.create_session_database(worker_id="gw0", suffix="abc123")

    create_query, create_params = captured[1]
    assert create_params is None
    assert isinstance(create_query, sql.Composed)
    assert "CREATE DATABASE" in create_query.as_string(None)


def test_pre_existing_database_is_not_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DisposableDatabaseManager(_template_url())

    class FakeCursor:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        autocommit = True

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    _patch_connect(monkeypatch, FakeConnection())

    with pytest.raises(DisposableDatabaseError, match="already exists"):
        manager.create_session_database(worker_id="gw0", suffix="abc123")

    assert manager.ownership is None


def test_cleanup_skips_drop_when_database_not_created() -> None:
    manager = DisposableDatabaseManager(_template_url())

    def fail_drop(*_args: object, **_kwargs: object) -> None:
        msg = "drop must not run"
        raise AssertionError(msg)

    manager._drop_database = fail_drop  # type: ignore[method-assign]
    manager.cleanup()


def test_create_failure_does_not_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DisposableDatabaseManager(_template_url())
    drop_calls: list[str] = []

    def fail_create(_name: str) -> None:
        msg = "create failed"
        raise DisposableDatabaseError(msg)

    def track_drop(name: str) -> None:
        drop_calls.append(name)

    monkeypatch.setattr(manager, "_create_database", fail_create)
    monkeypatch.setattr(manager, "_drop_database", track_drop)

    with pytest.raises(DisposableDatabaseError, match="create failed"):
        manager.create_session_database(worker_id="gw0", suffix="abc123")

    assert drop_calls == []
    assert manager.ownership is None


def test_cleanup_only_drops_owned_database(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DisposableDatabaseManager(_template_url())
    dropped: list[str] = []

    class FakeCursor:
        call_count = 0

        def execute(self, query: object, params: object = None) -> None:
            type(self).call_count += 1

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

    _patch_connect(monkeypatch, FakeConnection())
    monkeypatch.setattr(manager, "_terminate_connections", lambda *_args: None)
    monkeypatch.setattr(manager, "_drop_database", dropped.append)
    monkeypatch.setattr(manager, "_database_exists_by_name", lambda _name: False)

    manager.create_session_database(worker_id="gw0", suffix="abc123")
    manager.cleanup()

    assert dropped == ["cps_test_gw0_abc123"]


def test_reject_template_for_migrations() -> None:
    with pytest.raises(DisposableDatabaseError, match="must not run against template database"):
        reject_template_for_migrations(_template_url())


def test_build_database_url_preserves_driver_and_host() -> None:
    url = _disposable_url("cps_test_gw0_abc123")
    assert url == f"postgresql+psycopg://cps@{_TEST_HOST}/cps_test_gw0_abc123"


def test_insufficient_privilege_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    execute_count = 0

    class FakeCursor:
        def execute(self, query: object, params: object = None) -> None:
            nonlocal execute_count
            execute_count += 1
            if execute_count >= 2:
                raise psycopg.errors.InsufficientPrivilege("nope")

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

    _patch_connect(monkeypatch, FakeConnection())
    manager = DisposableDatabaseManager(_template_url())

    with pytest.raises(DisposableDatabaseError, match="lacks CREATE DATABASE privilege"):
        manager.create_session_database(worker_id="gw0", suffix="abc123")
