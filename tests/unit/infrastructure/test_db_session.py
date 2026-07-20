"""CPS-103 Task 1: async session factory."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from cps.infrastructure.db.session import create_session_factory


def test_session_module_does_not_create_session_at_import() -> None:
    with patch("sqlalchemy.ext.asyncio.async_sessionmaker") as sessionmaker:
        sys.modules.pop("cps.infrastructure.db.session", None)
        importlib.import_module("cps.infrastructure.db.session")
        sessionmaker.assert_not_called()


def test_create_session_factory_binds_engine_with_expected_options() -> None:
    engine = MagicMock(spec=AsyncEngine)

    factory = create_session_factory(engine)

    assert factory.kw["bind"] is engine
    assert factory.class_ is AsyncSession
    assert factory.kw["expire_on_commit"] is False


def test_create_session_factory_produces_independent_sessions() -> None:
    engine = MagicMock(spec=AsyncEngine)
    factory = create_session_factory(engine)

    first_session = factory()
    second_session = factory()

    assert first_session is not second_session
