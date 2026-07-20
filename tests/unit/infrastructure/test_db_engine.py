"""CPS-103 Task 1: async engine factory and declarative base naming."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base


def test_declarative_base_generates_expected_constraint_names() -> None:
    class SampleParent(Base):
        __tablename__ = "sample_parent"

        id: Mapped[int] = mapped_column(primary_key=True)

    class SampleChild(Base):
        __tablename__ = "sample_child"

        id: Mapped[int] = mapped_column(primary_key=True)
        parent_id: Mapped[int] = mapped_column(ForeignKey("sample_parent.id"))
        code: Mapped[str] = mapped_column(String(32))
        __table_args__ = (
            UniqueConstraint("code"),
            CheckConstraint("length(code) > 0", name="code_len"),
            Index(None, "parent_id"),
        )

    parent_table = SampleParent.__table__
    child_table = SampleChild.__table__

    assert parent_table.primary_key.name == "pk_sample_parent"
    assert child_table.primary_key.name == "pk_sample_child"

    foreign_keys = list(child_table.foreign_key_constraints)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].name == "fk_sample_child_parent_id_sample_parent"

    unique_constraints = [
        constraint
        for constraint in child_table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert len(unique_constraints) == 1
    assert unique_constraints[0].name == "uq_sample_child_code"

    indexes = list(child_table.indexes)
    assert len(indexes) == 1
    assert indexes[0].name == "ix_sample_child_parent_id"

    check_constraints = [
        constraint
        for constraint in child_table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert len(check_constraints) == 1
    assert check_constraints[0].name == "ck_sample_child_code_len"


def test_engine_module_does_not_create_engine_at_import() -> None:
    with patch("sqlalchemy.ext.asyncio.create_async_engine") as create_engine:
        sys.modules.pop("cps.infrastructure.db.engine", None)
        importlib.import_module("cps.infrastructure.db.engine")
        create_engine.assert_not_called()


def test_create_database_engine_passes_url_and_pool_options() -> None:
    from cps.infrastructure.db.engine import create_database_engine

    mock_engine = MagicMock()
    database_url = "postgresql+psycopg://user:" + "secret" + "@127.0.0.1:5432/cps"

    with patch(
        "cps.infrastructure.db.engine.create_async_engine",
        return_value=mock_engine,
    ) as create_engine:
        result = create_database_engine(database_url)

    create_engine.assert_called_once_with(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    assert result is mock_engine


def test_create_database_engine_does_not_log_database_url(caplog: pytest.LogCaptureFixture) -> None:
    from cps.infrastructure.db.engine import create_database_engine

    forbidden_token = "must-not-" + "appear"
    database_url = "postgresql+psycopg://cps:" + forbidden_token + "@127.0.0.1:5432/cps"

    with patch("cps.infrastructure.db.engine.create_async_engine", return_value=MagicMock()):
        create_database_engine(database_url)

    for record in caplog.records:
        assert forbidden_token not in record.getMessage()


def test_legacy_import_path_still_exports_url_helper() -> None:
    from cps.infrastructure import db as db_package
    from cps.infrastructure.db import to_psycopg_conninfo

    assert db_package.to_psycopg_conninfo is to_psycopg_conninfo


def test_db_package_does_not_keep_conflicting_module_file() -> None:
    from pathlib import Path

    module_file = Path("src/cps/infrastructure/db.py")
    package_dir = Path("src/cps/infrastructure/db")
    assert not module_file.exists()
    assert package_dir.is_dir()
