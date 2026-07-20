"""CPS-002: typed settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_production_settings_require_database_and_rabbitmq_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    monkeypatch.delenv("CPS_DATABASE_URL", raising=False)
    monkeypatch.delenv("CPS_RABBITMQ_URL", raising=False)

    from cps.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_development_settings_load_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPS_ENVIRONMENT", "development")
    monkeypatch.delenv("CPS_DATABASE_URL", raising=False)
    monkeypatch.delenv("CPS_RABBITMQ_URL", raising=False)

    from cps.config import Settings

    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.database_url.startswith("postgresql")
    assert settings.rabbitmq_url.startswith("amqp")
