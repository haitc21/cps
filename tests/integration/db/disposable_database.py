"""Disposable PostgreSQL database lifecycle for integration tests."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

import psycopg
from psycopg import sql

from tests.integration.db.database_url import (
    ALLOWED_TEST_DATABASE,
    admin_conninfo,
    parse_database_name,
    validate_test_database_url,
)

DISPOSABLE_NAME_PATTERN = re.compile(r"^cps_test_[a-z0-9_]+$")
SAFE_NAME_PART_PATTERN = re.compile(r"^[a-z0-9_]+$")
MAX_IDENTIFIER_BYTES = 63

CLEANUP_FAILED_MESSAGE = "disposable database cleanup failed"


class DisposableDatabaseError(RuntimeError):
    """Raised when disposable integration database lifecycle fails."""


@dataclass(frozen=True, slots=True)
class CleanupDiagnostic:
    phase: str
    exception_class: str


@dataclass(slots=True)
class DisposableDatabaseOwnership:
    database_name: str
    created_by_session: bool = False


class DisposableDatabaseManager:
    """Create, track, and cleanup one session-scoped disposable database."""

    def __init__(self, template_database_url: str) -> None:
        validate_test_database_url(template_database_url)
        self._template_database_url = template_database_url
        self._admin_conninfo = admin_conninfo(template_database_url)
        self.ownership: DisposableDatabaseOwnership | None = None
        self.database_url: str | None = None

    def create_session_database(self, *, worker_id: str, suffix: str | None = None) -> str:
        if self.ownership is not None:
            msg = "disposable database already created for this session"
            raise DisposableDatabaseError(msg)
        generated_suffix = suffix or secrets.token_hex(8)
        database_name = generate_database_name(worker_id=worker_id, suffix=generated_suffix)
        self._create_database(database_name)
        self.ownership = DisposableDatabaseOwnership(
            database_name=database_name,
            created_by_session=True,
        )
        self.database_url = build_database_url(self._template_database_url, database_name)
        return self.database_url

    def cleanup(self) -> None:
        if self.ownership is None or not self.ownership.created_by_session:
            return

        database_name = self.ownership.database_name
        diagnostics: list[CleanupDiagnostic] = []

        try:
            self._terminate_connections(database_name)
        except Exception as exc:
            diagnostics.append(CleanupDiagnostic("terminate_connections", exc.__class__.__name__))

        try:
            self._drop_database(database_name)
        except Exception as exc:
            diagnostics.append(CleanupDiagnostic("drop_database", exc.__class__.__name__))

        database_exists: bool | None = None
        try:
            database_exists = self._database_exists_by_name(database_name)
        except Exception as exc:
            diagnostics.append(CleanupDiagnostic("verify_absent", exc.__class__.__name__))

        if database_exists is None:
            detail = _format_cleanup_failure(diagnostics)
            raise DisposableDatabaseError(detail) from None

        if database_exists:
            detail = _format_cleanup_failure(diagnostics)
            raise DisposableDatabaseError(detail) from None

        self.ownership = None
        self.database_url = None

    def _create_database(self, database_name: str) -> None:
        validate_disposable_database_name(database_name)
        with psycopg.connect(self._admin_conninfo, autocommit=True) as connection:
            if self._database_exists(connection, database_name):
                msg = f"disposable database {database_name!r} already exists"
                raise DisposableDatabaseError(msg)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                    )
            except psycopg.errors.InsufficientPrivilege as exc:
                msg = "integration role lacks CREATE DATABASE privilege"
                raise DisposableDatabaseError(msg) from exc
            except psycopg.Error as exc:
                msg = f"failed to create disposable database {database_name!r}"
                raise DisposableDatabaseError(msg) from exc

    def _drop_database(self, database_name: str) -> None:
        validate_disposable_database_name(database_name)
        with psycopg.connect(self._admin_conninfo, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )

    def _terminate_connections(self, database_name: str) -> None:
        validate_disposable_database_name(database_name)
        with psycopg.connect(self._admin_conninfo, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (database_name,),
                )

    def _database_exists(self, connection: psycopg.Connection, database_name: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            return cursor.fetchone() is not None

    def _database_exists_by_name(self, database_name: str) -> bool:
        with psycopg.connect(self._admin_conninfo, autocommit=True) as connection:
            return self._database_exists(connection, database_name)


def _format_cleanup_failure(diagnostics: list[CleanupDiagnostic]) -> str:
    if not diagnostics:
        return CLEANUP_FAILED_MESSAGE
    detail = "; ".join(f"{item.phase}:{item.exception_class}" for item in diagnostics)
    return f"{CLEANUP_FAILED_MESSAGE} ({detail})"


def sanitize_name_part(part: str) -> str:
    sanitized = re.sub(r"[^a-z0-9_]", "", part.lower())
    if not sanitized or not SAFE_NAME_PART_PATTERN.fullmatch(sanitized):
        msg = f"invalid disposable database name part: {part!r}"
        raise DisposableDatabaseError(msg)
    return sanitized


def generate_database_name(*, worker_id: str, suffix: str) -> str:
    worker = sanitize_name_part(worker_id)
    suffix_part = sanitize_name_part(suffix)
    database_name = f"cps_test_{worker}_{suffix_part}"
    _validate_identifier_length(database_name)
    validate_disposable_database_name(database_name)
    return database_name


def _validate_identifier_length(database_name: str) -> None:
    if len(database_name.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        msg = "disposable database name exceeds PostgreSQL identifier limit (63 bytes)"
        raise DisposableDatabaseError(msg)


def is_disposable_database_name(database_name: str) -> bool:
    return database_name != ALLOWED_TEST_DATABASE and bool(
        DISPOSABLE_NAME_PATTERN.fullmatch(database_name)
    )


def validate_disposable_database_name(database_name: str) -> None:
    if database_name == ALLOWED_TEST_DATABASE:
        msg = "template database cps_test must not be used as a disposable target"
        raise DisposableDatabaseError(msg)
    if not DISPOSABLE_NAME_PATTERN.fullmatch(database_name):
        msg = f"invalid disposable database name: {database_name!r}"
        raise DisposableDatabaseError(msg)
    _validate_identifier_length(database_name)


def reject_template_for_migrations(database_url: str) -> None:
    database_name = parse_database_name(database_url)
    if database_name == ALLOWED_TEST_DATABASE:
        msg = "Alembic must not run against template database cps_test"
        raise DisposableDatabaseError(msg)
    validate_disposable_database_name(database_name)


def build_database_url(template_database_url: str, database_name: str) -> str:
    validate_disposable_database_name(database_name)
    normalized = template_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    rebuilt = parsed._replace(path=f"/{database_name}").geturl()
    if template_database_url.startswith("postgresql+psycopg://"):
        return rebuilt.replace("postgresql://", "postgresql+psycopg://", 1)
    return rebuilt


def read_worker_id() -> str:
    import os

    return os.environ.get("PYTEST_XDIST_WORKER", "master")
