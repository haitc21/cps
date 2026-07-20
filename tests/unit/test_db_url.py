"""Database URL helper tests."""

from __future__ import annotations

from cps.infrastructure.db import to_psycopg_conninfo


def test_to_psycopg_conninfo_strips_sqlalchemy_driver() -> None:
    assert (
        to_psycopg_conninfo("postgresql+psycopg://cps:secret@127.0.0.1:5432/cps")
        == "postgresql://cps:secret@127.0.0.1:5432/cps"
    )


def test_to_psycopg_conninfo_strips_psycopg_async_driver() -> None:
    assert (
        to_psycopg_conninfo("postgresql+psycopg_async://cps:secret@127.0.0.1:5432/cps")
        == "postgresql://cps:secret@127.0.0.1:5432/cps"
    )
