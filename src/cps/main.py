"""FastAPI application factory for CPS."""

from __future__ import annotations

from fastapi import FastAPI

from cps.api.errors import register_error_handlers
from cps.api.health import router as health_router
from cps.config import Settings, get_settings
from cps.infrastructure.health import HealthChecks
from cps.observability.logging import configure_logging
from cps.observability.middleware import CorrelationIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the CPS ASGI application."""
    resolved = settings or get_settings()
    configure_logging(level=resolved.log_level, service_name=resolved.service_name)

    app = FastAPI(title="CPS", version="0.1.0")
    app.state.settings = resolved
    app.state.health_checks = HealthChecks(resolved)
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    return app
