"""FastAPI application factory for CPS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cps.api.errors import register_error_handlers
from cps.api.health import router as health_router
from cps.api.routers.connections import router as connections_router
from cps.api.routers.credentials import router as credentials_router
from cps.api.routers.operations import router as operations_router
from cps.api.routers.providers import router as providers_router
from cps.config import Settings, get_settings
from cps.infrastructure.db.engine import create_database_engine
from cps.infrastructure.db.session import create_session_factory
from cps.infrastructure.health import HealthChecks
from cps.observability.logging import configure_logging
from cps.observability.middleware import CorrelationIdMiddleware
from cps.security.credentials import AesGcmCredentialCipher, MappingCredentialKeyProvider


def _create_base_app(resolved: Settings, *, title: str) -> tuple[FastAPI, object]:
    configure_logging(level=resolved.log_level, service_name=resolved.service_name)

    engine = create_database_engine(resolved.require_database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.database_engine = engine
    app.state.session_factory = create_session_factory(engine)
    credential_cipher = None
    if resolved.credential_key_ring:
        credential_cipher = AesGcmCredentialCipher(
            MappingCredentialKeyProvider(resolved.require_credential_keys)
        )
    app.state.credential_cipher = credential_cipher
    app.state.health_checks = HealthChecks(resolved)
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    return app, engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the public CPS application; internal routes use a separate listener."""
    resolved = settings or get_settings()
    app, _engine = _create_base_app(resolved, title="CPS")
    app.include_router(providers_router)
    app.include_router(credentials_router)
    app.include_router(connections_router)
    app.include_router(operations_router)
    return app


def create_internal_app(settings: Settings | None = None) -> FastAPI:
    """Create the private CPS listener containing only health and resolver routes."""
    from cps.api.routers.internal import router as internal_router

    resolved = settings or get_settings()
    app, _engine = _create_base_app(resolved, title="CPS Internal")
    app.include_router(internal_router)
    return app
