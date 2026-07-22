"""Public API dependency wiring for database transaction ownership."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request

from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


async def get_uow(request: Request) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    factory = request.app.state.session_factory
    async with SqlAlchemyUnitOfWork(factory) as uow:
        uow.session.info["settings"] = request.app.state.settings
        uow.session.info["credential_cipher"] = request.app.state.credential_cipher
        yield uow
