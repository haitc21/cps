"""Typed request principal derived from a verified Keycloak JWT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cps.security.auth.roles import (
    CMP_ADMIN,
    extract_cmp_roles,
    has_admin_access,
    has_member_access,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Safe identity context exposed to API handlers."""

    subject: str
    roles: frozenset[str]
    client_id: str
    preferred_username: str | None = None

    @classmethod
    def from_claims(cls, claims: dict[str, Any], *, client_id: str) -> AuthenticatedPrincipal:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            msg = "token subject is missing"
            raise ValueError(msg)
        preferred_username = claims.get("preferred_username")
        username = preferred_username if isinstance(preferred_username, str) else None
        return cls(
            subject=subject,
            roles=extract_cmp_roles(claims, client_id),
            client_id=client_id,
            preferred_username=username,
        )

    def is_admin(self) -> bool:
        return CMP_ADMIN in self.roles

    def is_member(self) -> bool:
        return has_member_access(self.roles)

    def can_access_admin_routes(self) -> bool:
        return has_admin_access(self.roles)

    def can_access_member_routes(self) -> bool:
        return has_member_access(self.roles)
