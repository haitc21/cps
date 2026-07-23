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


def test_production_settings_require_valid_credential_key_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    monkeypatch.setenv("CPS_DATABASE_URL", "postgresql+psycopg://cps:password@db:5432/cps")
    monkeypatch.setenv("CPS_RABBITMQ_URL", "amqp://cmp:password@rabbitmq:5672/cmp")
    monkeypatch.delenv("CPS_CREDENTIAL_KEY_RING", raising=False)

    from cps.config import Settings

    with pytest.raises(ValidationError, match="CPS_CREDENTIAL_KEY_RING"):
        Settings(_env_file=None)


def test_production_settings_accept_key_ring_with_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    monkeypatch.setenv("CPS_DATABASE_URL", "postgresql+psycopg://cps:password@db:5432/cps")
    monkeypatch.setenv("CPS_RABBITMQ_URL", "amqp://cmp:password@rabbitmq:5672/cmp")
    monkeypatch.setenv("CPS_CREDENTIAL_KEY_RING", f"v1:{base64.b64encode(b'k' * 32).decode()}")

    from cps.config import Settings

    settings = Settings(_env_file=None)
    assert settings.require_credential_keys["v1"] == b"k" * 32


def test_development_settings_load_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPS_ENVIRONMENT", "development")
    monkeypatch.delenv("CPS_DATABASE_URL", raising=False)
    monkeypatch.delenv("CPS_RABBITMQ_URL", raising=False)

    from cps.config import Settings

    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.database_url.startswith("postgresql")
    assert settings.rabbitmq_url.startswith("amqp")
