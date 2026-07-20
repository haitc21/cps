"""Unit tests for disposable database cleanup failure paths."""

from __future__ import annotations

import traceback

import pytest

from tests.integration.db.database_url import ALLOWED_TEST_DATABASE
from tests.integration.db.disposable_database import (
    CLEANUP_FAILED_MESSAGE,
    DisposableDatabaseError,
    DisposableDatabaseManager,
    DisposableDatabaseOwnership,
)

_TEST_HOST = "127.0.0.1:5432"


def _template_url() -> str:
    return f"postgresql+psycopg://cps@{_TEST_HOST}/{ALLOWED_TEST_DATABASE}"


def _owned_manager(database_name: str = "cps_test_gw0_abc123") -> DisposableDatabaseManager:
    manager = DisposableDatabaseManager(_template_url())
    manager.ownership = DisposableDatabaseOwnership(
        database_name=database_name, created_by_session=True
    )
    manager.database_url = f"postgresql+psycopg://cps@{_TEST_HOST}/{database_name}"
    return manager


def test_terminate_failure_still_attempts_drop() -> None:
    manager = _owned_manager()
    drop_calls: list[str] = []

    def fail_terminate(_name: str) -> None:
        msg = "terminate failed"
        raise RuntimeError(msg)

    manager._terminate_connections = fail_terminate  # type: ignore[method-assign]
    manager._drop_database = drop_calls.append  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: False  # type: ignore[method-assign]

    manager.cleanup()

    assert drop_calls == ["cps_test_gw0_abc123"]
    assert manager.ownership is None


def test_drop_failure_keeps_ownership() -> None:
    manager = _owned_manager()

    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]

    def fail_drop(_name: str) -> None:
        msg = "drop failed"
        raise RuntimeError(msg)

    manager._drop_database = fail_drop  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: True  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError, match=CLEANUP_FAILED_MESSAGE):
        manager.cleanup()

    assert manager.ownership is not None
    assert manager.ownership.database_name == "cps_test_gw0_abc123"


def test_cleanup_retry_after_drop_failure() -> None:
    manager = _owned_manager()
    attempts = {"count": 0}

    def flaky_drop(_name: str) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            msg = "drop failed once"
            raise RuntimeError(msg)

    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = flaky_drop  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: attempts["count"] == 1  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError, match=CLEANUP_FAILED_MESSAGE):
        manager.cleanup()

    manager._database_exists_by_name = lambda _name: False  # type: ignore[method-assign]
    manager.cleanup()

    assert attempts["count"] == 2
    assert manager.ownership is None


def test_terminate_and_drop_failure_has_safe_diagnostics() -> None:
    manager = _owned_manager()

    def fail_terminate(_name: str) -> None:
        msg = "secret-host terminate detail"
        raise RuntimeError(msg)

    def fail_drop(_name: str) -> None:
        msg = "secret credential drop detail"
        raise ValueError(msg)

    manager._terminate_connections = fail_terminate  # type: ignore[method-assign]
    manager._drop_database = fail_drop  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: True  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError) as exc_info:
        manager.cleanup()

    message = str(exc_info.value)
    assert CLEANUP_FAILED_MESSAGE in message
    assert "terminate_connections:RuntimeError" in message
    assert "drop_database:ValueError" in message
    assert "secret" not in message


def test_cleanup_success_clears_ownership() -> None:
    manager = _owned_manager()
    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = lambda _name: None  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: False  # type: ignore[method-assign]

    manager.cleanup()

    assert manager.ownership is None
    assert manager.database_url is None


def test_cleanup_when_not_owned_is_noop() -> None:
    manager = DisposableDatabaseManager(_template_url())
    called = {"terminate": False, "drop": False}

    manager._terminate_connections = lambda _name: called.__setitem__("terminate", True)  # type: ignore[method-assign]
    manager._drop_database = lambda _name: called.__setitem__("drop", True)  # type: ignore[method-assign]

    manager.cleanup()

    assert called == {"terminate": False, "drop": False}


def test_drop_rejects_template_name() -> None:
    manager = DisposableDatabaseManager(_template_url())

    with pytest.raises(DisposableDatabaseError, match="template database cps_test"):
        manager._drop_database(ALLOWED_TEST_DATABASE)


def test_cleanup_is_idempotent_after_success() -> None:
    manager = _owned_manager()
    drop_calls: list[str] = []
    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = drop_calls.append  # type: ignore[method-assign]
    manager._database_exists_by_name = lambda _name: False  # type: ignore[method-assign]

    manager.cleanup()
    manager.cleanup()

    assert drop_calls == ["cps_test_gw0_abc123"]


def test_verify_failure_is_sanitized_and_keeps_ownership() -> None:
    manager = _owned_manager()
    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = lambda _name: None  # type: ignore[method-assign]

    def fail_verify(_name: str) -> bool:
        msg = "postgresql://cps:must-not-leak@secret-host/cps_test"
        raise RuntimeError(msg)

    manager._database_exists_by_name = fail_verify  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError) as exc_info:
        manager.cleanup()

    message = str(exc_info.value)
    formatted = "".join(
        traceback.TracebackException.from_exception(exc_info.value).format(chain=True)
    )
    assert "verify_absent:RuntimeError" in message
    assert "must-not-leak" not in message
    assert "secret-host" not in message
    assert "must-not-leak" not in formatted
    assert "secret-host" not in formatted
    assert manager.ownership is not None
    assert manager.database_url is not None


def test_verify_failure_preserves_earlier_cleanup_diagnostics() -> None:
    manager = _owned_manager()

    def fail_terminate(_name: str) -> None:
        raise ValueError("raw terminate detail")

    def fail_drop(_name: str) -> None:
        raise OSError("raw drop detail")

    def fail_verify(_name: str) -> bool:
        raise RuntimeError("raw verify detail")

    manager._terminate_connections = fail_terminate  # type: ignore[method-assign]
    manager._drop_database = fail_drop  # type: ignore[method-assign]
    manager._database_exists_by_name = fail_verify  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError) as exc_info:
        manager.cleanup()

    message = str(exc_info.value)
    assert "terminate_connections:ValueError" in message
    assert "drop_database:OSError" in message
    assert "verify_absent:RuntimeError" in message
    assert "raw" not in message
    assert manager.ownership is not None


def test_cleanup_retry_after_verify_failure_clears_state() -> None:
    manager = _owned_manager()
    manager._terminate_connections = lambda _name: None  # type: ignore[method-assign]
    manager._drop_database = lambda _name: None  # type: ignore[method-assign]
    verify_attempts = {"count": 0}

    def flaky_verify(_name: str) -> bool:
        verify_attempts["count"] += 1
        if verify_attempts["count"] == 1:
            raise RuntimeError("temporary verification failure")
        return False

    manager._database_exists_by_name = flaky_verify  # type: ignore[method-assign]

    with pytest.raises(DisposableDatabaseError):
        manager.cleanup()

    manager.cleanup()

    assert verify_attempts["count"] == 2
    assert manager.ownership is None
    assert manager.database_url is None


def test_cleanup_does_not_swallow_control_flow_exception() -> None:
    manager = _owned_manager()

    def interrupt_terminate(_name: str) -> None:
        raise KeyboardInterrupt

    manager._terminate_connections = interrupt_terminate  # type: ignore[method-assign]

    with pytest.raises(KeyboardInterrupt):
        manager.cleanup()

    assert manager.ownership is not None
