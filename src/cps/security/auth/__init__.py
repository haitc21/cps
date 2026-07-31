"""Keycloak JWT authentication for the public CPS API."""

from __future__ import annotations

from cps.security.auth.middleware import (
    KeycloakAuthMiddleware,
    create_keycloak_verifier,
    get_current_principal,
    install_keycloak_auth_middleware,
    is_public_path,
    require_admin,
    required_access_for_path,
)
from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.roles import CMP_ADMIN, CMP_MEMBER, extract_cmp_roles, normalize_cmp_roles
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

__all__ = [
    "AuthenticatedPrincipal",
    "CMP_ADMIN",
    "CMP_MEMBER",
    "JwtVerificationError",
    "KeycloakAuthMiddleware",
    "KeycloakJwtVerifier",
    "create_keycloak_verifier",
    "extract_cmp_roles",
    "get_current_principal",
    "install_keycloak_auth_middleware",
    "is_public_path",
    "normalize_cmp_roles",
    "require_admin",
    "required_access_for_path",
]
