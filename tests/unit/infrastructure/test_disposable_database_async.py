"""Unit tests for disposable database async-engine cleanup boundaries."""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path

from tests.integration.db.database_url import ALLOWED_TEST_DATABASE
from tests.integration.db.disposable_database import (
    DisposableDatabaseManager,
    DisposableDatabaseOwnership,
)

ROOT = Path(__file__).resolve().parents[3]
DISPOSABLE_SOURCE = ROOT / "tests" / "integration" / "db" / "disposable_database.py"
CONFTEST_SOURCE = ROOT / "tests" / "integration" / "db" / "conftest.py"


def test_disposable_database_manager_source_has_no_asyncio_run() -> None:
    source = DISPOSABLE_SOURCE.read_text(encoding="utf-8")
    assert "asyncio.run" not in source
    assert "register_engine" not in source


def test_db_engine_fixture_disposes_in_async_fixture_only() -> None:
    source = CONFTEST_SOURCE.read_text(encoding="utf-8")
    assert "register_engine" not in source
    assert "await engine.dispose()" in source


def test_cleanup_from_running_event_loop_has_no_coroutine_warning() -> None:
    manager = DisposableDatabaseManager(
        f"postgresql+psycopg://cps@127.0.0.1:5432/{ALLOWED_TEST_DATABASE}"
    )
    manager.ownership = DisposableDatabaseOwnership(
        database_name="cps_test_gw0_abc123",
        created_by_session=True,
    )
    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = lambda _name: None  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: False  # type: ignore[method-assign]

    async def run_cleanup() -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manager.cleanup()
        runtime_warnings = [item for item in caught if issubclass(item.category, RuntimeWarning)]
        assert runtime_warnings == []

    asyncio.run(run_cleanup())
