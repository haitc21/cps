"""Bearer authentication middleware and FastAPI dependencies."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from cps.config import Settings
from cps.contracts.errors import AuthenticationError, AuthorizationError, CommonError
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

_PUBLIC_PATH_PREFIXES = ("/health/",)
_PUBLIC_PATHS = frozenset({"/metrics"})


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


def required_access_for_path(path: str) -> str | None:
    """Return ``admin``, ``member``, or ``None`` when auth is not required."""
    if is_public_path(path):
        return None
    if path == "/api/v1/admin" or path.startswith("/api/v1/admin/"):
        return "admin"
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return "member"
    return None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _error_response(request: Request, error: CommonError, status_code: int) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={"error": error.model_dump(mode="json"), "correlation_id": correlation_id},
        headers={"x-correlation-id": correlation_id},
    )


class KeycloakAuthMiddleware(BaseHTTPMiddleware):
    """Enforce JWT bearer authentication on protected public API routes."""

    def __init__(
        self,
        app: Any,
        *,
        verifier: KeycloakJwtVerifier | None,
    ) -> None:
        super().__init__(app)
        self._verifier = verifier

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        required_access = required_access_for_path(request.url.path)
        if required_access is None:
            return await call_next(request)

        token = _extract_bearer_token(request.headers.get("authorization"))
        if token is None:
            return _error_response(request, AuthenticationError().to_common_error(), 401)

        if self._verifier is None:
            return _error_response(
                request,
                AuthenticationError("Authentication service unavailable").to_common_error(),
                401,
            )

        try:
            principal = await self._verifier.verify(token)
        except JwtVerificationError:
            return _error_response(request, AuthenticationError().to_common_error(), 401)

        if required_access == "admin" and not principal.can_access_admin_routes():
            return _error_response(request, AuthorizationError().to_common_error(), 403)
        if required_access == "member" and not principal.is_member():
            return _error_response(request, AuthorizationError().to_common_error(), 403)

        request.state.principal = principal
        return await call_next(request)


def get_current_principal(request: Request) -> Any:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthenticationError
    return principal


def require_admin(request: Request) -> Any:
    principal = get_current_principal(request)
    if not principal.can_access_admin_routes():
        raise AuthorizationError
    return principal


def create_keycloak_verifier(settings: Settings) -> KeycloakJwtVerifier:
    return KeycloakJwtVerifier.from_settings(
        issuer=settings.keycloak_issuer,
        client_id=settings.keycloak_client_id,
        audience=settings.keycloak_audience,
        jwks_cache_ttl_seconds=settings.keycloak_jwks_cache_ttl_seconds,
    )


def install_keycloak_auth_middleware(app: Any, settings: Settings) -> None:
    verifier = create_keycloak_verifier(settings)
    app.state.keycloak_verifier = verifier
    app.add_middleware(
        KeycloakAuthMiddleware,
        verifier=verifier,
    )
