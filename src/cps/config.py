"""Typed application settings for CPS."""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Environment-backed CPS configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: EnvironmentName = "development"
    service_name: str = "cps"
    log_level: str = "INFO"
    database_url: str | None = None
    rabbitmq_url: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    credential_active_key_version: str = "v1"
    credential_key_ring: str | None = None
    operation_timeout_seconds: int = 900
    recovery_interval_seconds: float = 5.0
    inventory_scheduler_enabled: bool = False
    inventory_scheduler_interval_seconds: float = 60.0
    inventory_scheduler_jitter_seconds: float = 10.0

    @model_validator(mode="after")
    def validate_required_urls(self) -> Settings:
        if self.environment == "development":
            if not self.database_url:
                self.database_url = "postgresql+psycopg://cps:cps_dev_password@127.0.0.1:5432/cps"
            if not self.rabbitmq_url:
                self.rabbitmq_url = "amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp"
            return self

        if self.environment == "test":
            if not self.database_url:
                self.database_url = "postgresql+psycopg://cps:cps_dev_password@127.0.0.1:5432/cps"
            if not self.rabbitmq_url:
                self.rabbitmq_url = "amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp"
            return self

        missing: list[str] = []
        if not self.database_url:
            missing.append("CPS_DATABASE_URL")
        if not self.rabbitmq_url:
            missing.append("CPS_RABBITMQ_URL")
        if not self.credential_key_ring:
            missing.append("CPS_CREDENTIAL_KEY_RING")
        else:
            try:
                _ = self.require_credential_keys
            except RuntimeError:
                missing.append("CPS_CREDENTIAL_KEY_RING (invalid)")
        if missing:
            raise ValueError(f"missing required production settings: {', '.join(missing)}")
        return self

    @property
    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError("database_url is not configured")
        return self.database_url

    @property
    def require_rabbitmq_url(self) -> str:
        if not self.rabbitmq_url:
            raise RuntimeError("rabbitmq_url is not configured")
        return self.rabbitmq_url

    @property
    def require_credential_keys(self) -> dict[str, bytes]:
        """Parse the external key ring and fail closed without exposing values."""
        if not self.credential_key_ring:
            raise RuntimeError("credential encryption key ring is not configured")
        keys: dict[str, bytes] = {}
        try:
            for item in self.credential_key_ring.split(","):
                version, encoded = item.split(":", 1)
                if not version or not encoded:
                    raise ValueError
                key = base64.b64decode(encoded, validate=True)
                if len(key) != 32:
                    raise ValueError
                keys[version] = key
        except (ValueError, UnicodeError, binascii.Error):
            raise RuntimeError("credential encryption key ring is invalid") from None
        if self.credential_active_key_version not in keys:
            raise RuntimeError("active credential encryption key is unavailable")
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
