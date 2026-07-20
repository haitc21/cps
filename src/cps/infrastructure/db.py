"""Database URL helpers for CPS."""

from __future__ import annotations


def to_psycopg_conninfo(database_url: str) -> str:
    """Convert a SQLAlchemy async URL to a psycopg connection string."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgresql+psycopg_async://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg_async://")
    return database_url
