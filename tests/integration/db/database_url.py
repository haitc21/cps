"""Test database URL validation for integration tests."""

from __future__ import annotations

import os
from urllib.parse import urlparse

ALLOWED_TEST_DATABASE = "cps_test"
FORBIDDEN_DATABASES = frozenset({"cps", "postgres", "template0", "template1", ""})


class DatabaseUrlValidationError(ValueError):
    """Raised when integration test database URL is missing or unsafe."""


def parse_database_name(database_url: str) -> str:
    if not database_url.strip():
        msg = "database URL must not be empty"
        raise DatabaseUrlValidationError(msg)
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgresql", "postgres"}:
        msg = "database URL must use a PostgreSQL scheme"
        raise DatabaseUrlValidationError(msg)
    return parsed.path.lstrip("/")


def validate_test_database_url(database_url: str) -> None:
    db_name = parse_database_name(database_url)
    if not db_name:
        msg = "database URL must include a database name"
        raise DatabaseUrlValidationError(msg)
    if db_name in FORBIDDEN_DATABASES:
        msg = f"integration tests must not use forbidden database {db_name!r}"
        raise DatabaseUrlValidationError(msg)
    if db_name != ALLOWED_TEST_DATABASE:
        msg = f"integration tests must use database {ALLOWED_TEST_DATABASE!r}, got {db_name!r}"
        raise DatabaseUrlValidationError(msg)


def require_integration_enabled() -> None:
    if os.getenv("CPS_RUN_INTEGRATION", "0") != "1":
        msg = "integration disabled; set CPS_RUN_INTEGRATION=1"
        raise DatabaseUrlValidationError(msg)


def require_test_database_url() -> str:
    require_integration_enabled()
    database_url = os.getenv("CPS_TEST_DATABASE_URL")
    if not database_url:
        msg = "CPS_TEST_DATABASE_URL is required when CPS_RUN_INTEGRATION=1"
        raise DatabaseUrlValidationError(msg)
    validate_test_database_url(database_url)
    return database_url


def admin_conninfo(database_url: str) -> str:
    validate_test_database_url(database_url)
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    admin_path = parsed._replace(path="/postgres").geturl()
    return admin_path.replace("postgresql://", "postgresql://", 1)
