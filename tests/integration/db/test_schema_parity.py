"""CPS-103 Task 2: model–migration parity integration test."""

from __future__ import annotations

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from cps.infrastructure.db.base import Base

pytestmark = pytest.mark.integration


def _normalize_diff(diff: list[object]) -> list[tuple[str, ...]]:
    normalized: list[tuple[str, ...]] = []
    for item in diff:
        if isinstance(item, tuple):
            normalized.append(tuple(str(part) for part in item))
        else:
            normalized.append((str(item),))
    return normalized


def test_model_migration_parity_has_no_schema_diff(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    sync_url = migrated_database.replace("postgresql+psycopg://", "postgresql+psycopg://", 1)
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)
    assert _normalize_diff(diff) == []
