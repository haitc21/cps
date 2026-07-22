"""Regression tests for integration opt-out behavior."""

from __future__ import annotations

import pytest

from tests.integration.db.conftest import require_integration_template_database_url
from tests.integration.messaging.conftest import require_rabbitmq_base_url


def test_db_integration_fails_when_enabled_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPS_RUN_INTEGRATION", "1")
    monkeypatch.delenv("CPS_TEST_DATABASE_URL", raising=False)
    with pytest.raises(BaseException, match="CPS_TEST_DATABASE_URL"):
        require_integration_template_database_url()


def test_messaging_integration_fails_when_enabled_without_rabbitmq_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPS_RUN_INTEGRATION", "1")
    monkeypatch.delenv("CPS_TEST_RABBITMQ_URL", raising=False)
    with pytest.raises(BaseException, match="CPS_TEST_RABBITMQ_URL"):
        require_rabbitmq_base_url()


def test_messaging_integration_skips_when_run_integration_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CPS_RUN_INTEGRATION", raising=False)
    with pytest.raises(pytest.skip.Exception, match="integration disabled"):
        require_rabbitmq_base_url()


def test_db_integration_skips_when_run_integration_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CPS_RUN_INTEGRATION", raising=False)
    with pytest.raises(pytest.skip.Exception, match="integration disabled"):
        require_integration_template_database_url()
