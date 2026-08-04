"""Typed request principal derived from a verified Keycloak JWT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cps.security.auth.roles import (
    CMP_ADMIN,
    extract_client_roles,
    extract_cmp_roles,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Safe identity context exposed to API handlers."""

    subject: str
    roles: frozenset[str]
    client_roles: frozenset[str]
    client_id: str
    preferred_username: str | None = None
    email: str | None = None

    @classmethod
    def from_claims(cls, claims: dict[str, Any], *, client_id: str) -> AuthenticatedPrincipal:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            msg = "token subject is missing"
            raise ValueError(msg)
        preferred_username = claims.get("preferred_username")
        username = preferred_username if isinstance(preferred_username, str) else None
        email_claim = claims.get("email")
        email = email_claim if isinstance(email_claim, str) else None
        return cls(
            subject=subject,
            roles=extract_cmp_roles(claims, client_id),
            client_roles=extract_client_roles(claims, client_id),
            client_id=client_id,
            preferred_username=username,
            email=email,
        )

    def is_admin(self) -> bool:
        return CMP_ADMIN in self.roles

    def is_member(self) -> bool:
        return "member" in self.client_roles

    def can_access_admin_routes(self) -> bool:
        return "admin:admin" in self.client_roles

    def can_access_member_routes(self) -> bool:
        return self.is_member()

    def is_app_owner(self, app_owner: str | None) -> bool:
        """Match the configured owner against identity from a verified JWT."""
        if app_owner is None:
            return False
        expected = app_owner.strip().casefold()
        if not expected:
            return False
        identities = (self.email, self.preferred_username)
        return any(
            value is not None and value.strip().casefold() == expected for value in identities
        )
