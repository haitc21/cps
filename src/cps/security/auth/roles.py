"""Canonical CMP role extraction from Keycloak JWT claims."""

from __future__ import annotations

from typing import Any

CMP_ADMIN = "admin"
CMP_MEMBER = "member"

_ROLE_ALIASES: dict[str, str] = {
    "admin": CMP_ADMIN,
    "admin:admin": CMP_ADMIN,
    "member": CMP_MEMBER,
    "member:signature": CMP_MEMBER,
}


def normalize_cmp_roles(raw_roles: list[str] | tuple[str, ...] | set[str]) -> frozenset[str]:
    """Map deployed Keycloak role aliases to canonical CPS roles."""
    canonical: set[str] = set()
    for role in raw_roles:
        mapped = _ROLE_ALIASES.get(role)
        if mapped is not None:
            canonical.add(mapped)
    return frozenset(canonical)


def extract_cmp_roles(claims: dict[str, Any], client_id: str) -> frozenset[str]:
    """Read client roles from ``resource_access[client_id].roles``."""
    resource_access = claims.get("resource_access")
    if not isinstance(resource_access, dict):
        return frozenset()
    client_access = resource_access.get(client_id)
    if not isinstance(client_access, dict):
        return frozenset()
    raw_roles = client_access.get("roles")
    if not isinstance(raw_roles, list):
        return frozenset()
    role_names = [role for role in raw_roles if isinstance(role, str)]
    return normalize_cmp_roles(role_names)


def has_member_access(roles: frozenset[str]) -> bool:
    """Return whether the principal may access member-facing routes."""
    return CMP_ADMIN in roles or CMP_MEMBER in roles


def has_admin_access(roles: frozenset[str]) -> bool:
    """Return whether the principal may access admin-facing routes."""
    return CMP_ADMIN in roles
