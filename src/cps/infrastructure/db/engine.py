"""Async SQLAlchemy engine factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given database URL."""
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
