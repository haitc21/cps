"""Bearer authentication middleware and FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Header, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from cps.api.response import envelope_from_domain_error
from cps.config import Settings
from cps.contracts.errors import (
    AuthenticationError,
    AuthorizationError,
    AuthorizationServiceUnavailableError,
    DomainError,
)
from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.tms import HttpTmsMembershipAuthorizer, TmsAuthorizationUnavailable
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

_PUBLIC_PATH_PREFIXES = ("/health/",)
_PUBLIC_PATHS = frozenset({"/metrics"})
ORG_SCOPE_HEADER = "X-Org-ID"
WS_SCOPE_HEADER = "X-WS-ID"
_MEMBER_SCOPE_HEADER_DESCRIPTION = (
    "Required for authenticated member requests unless the caller is the configured APP_OWNER."
)
_ORG_SCOPE_HEADER_DESCRIPTION = (
    f"Organization identifier for TMS membership authorization. {_MEMBER_SCOPE_HEADER_DESCRIPTION}"
)
_WS_SCOPE_HEADER_DESCRIPTION = (
    f"Workspace identifier for TMS membership authorization. {_MEMBER_SCOPE_HEADER_DESCRIPTION}"
)


def document_member_scope_headers(
    x_org_id: Annotated[
        str | None,
        Header(
            alias=ORG_SCOPE_HEADER,
            description=_ORG_SCOPE_HEADER_DESCRIPTION,
        ),
    ] = None,
    x_ws_id: Annotated[
        str | None,
        Header(
            alias=WS_SCOPE_HEADER,
            description=_WS_SCOPE_HEADER_DESCRIPTION,
        ),
    ] = None,
) -> None:
    """Declare member scope headers in OpenAPI; enforced by KeycloakAuthMiddleware."""
    return None


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


def _error_response(
    request: Request,
    exc: DomainError,
) -> JSONResponse:
    return envelope_from_domain_error(request, exc)


class KeycloakAuthMiddleware(BaseHTTPMiddleware):
    """Enforce JWT bearer authentication on protected public API routes."""

    def __init__(
        self,
        app: Any,
        *,
        verifier: KeycloakJwtVerifier | None,
        tms_authorizer: Callable[..., Awaitable[bool]],
        app_owner: str | None,
    ) -> None:
        super().__init__(app)
        self._verifier = verifier
        self._tms_authorizer = tms_authorizer
        self._app_owner = app_owner

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
            return _error_response(request, AuthenticationError())

        if self._verifier is None:
            return _error_response(
                request,
                AuthenticationError("Authentication service unavailable"),
            )

        try:
            principal = await self._verifier.verify(token)
        except JwtVerificationError:
            return _error_response(request, AuthenticationError())

        request.state.principal = principal
        if principal.is_app_owner(self._app_owner):
            return await call_next(request)

        if required_access == "admin" and not principal.can_access_admin_routes():
            return _error_response(request, AuthorizationError())
        if required_access == "member":
            if not principal.can_access_member_routes():
                return _error_response(request, AuthorizationError())
            org_id = _validated_scope_header(request.headers.get(ORG_SCOPE_HEADER.lower()))
            workspace_id = _validated_scope_header(request.headers.get(WS_SCOPE_HEADER.lower()))
            if org_id is None or workspace_id is None:
                return _error_response(request, AuthorizationError())
            try:
                allowed = await self._tms_authorizer(
                    bearer_token=token,
                    subject=principal.subject,
                    org_id=org_id,
                    workspace_id=workspace_id,
                )
            except TmsAuthorizationUnavailable:
                return _error_response(request, AuthorizationServiceUnavailableError())
            if not allowed:
                return _error_response(request, AuthorizationError())
            request.state.org_id = org_id
            request.state.workspace_id = workspace_id

        return await call_next(request)


def _validated_scope_header(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        return None
    return normalized


def get_current_principal(request: Request) -> AuthenticatedPrincipal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, AuthenticatedPrincipal):
        raise AuthenticationError
    return principal


def _is_app_owner_request(request: Request, principal: AuthenticatedPrincipal) -> bool:
    settings = getattr(request.app.state, "settings", None)
    app_owner = getattr(settings, "app_owner", None)
    return bool(principal.is_app_owner(app_owner))


def require_admin(request: Request) -> AuthenticatedPrincipal:
    principal = get_current_principal(request)
    if _is_app_owner_request(request, principal):
        return principal
    if not principal.can_access_admin_routes():
        raise AuthorizationError
    return principal


def require_member(request: Request) -> AuthenticatedPrincipal:
    principal = get_current_principal(request)
    if _is_app_owner_request(request, principal):
        return principal
    if not principal.is_member():
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
    authorizer = HttpTmsMembershipAuthorizer(
        base_url=settings.require_tms_base_url,
        connect_timeout_seconds=settings.tms_connect_timeout_seconds,
        read_timeout_seconds=settings.tms_read_timeout_seconds,
    )
    app.state.keycloak_verifier = verifier
    app.state.tms_authorizer = authorizer
    app.add_middleware(
        KeycloakAuthMiddleware,
        verifier=verifier,
        tms_authorizer=authorizer.authorize,
        app_owner=settings.app_owner,
    )
