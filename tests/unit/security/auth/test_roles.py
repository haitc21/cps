"""CMP role normalization tests."""

from __future__ import annotations

from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.roles import (
    extract_cmp_roles,
    has_admin_access,
    has_member_access,
    normalize_cmp_roles,
)


def test_normalize_cmp_roles_maps_deployed_aliases() -> None:
    assert normalize_cmp_roles(["admin"]) == frozenset({"admin"})
    assert normalize_cmp_roles(["admin:admin"]) == frozenset({"admin"})
    assert normalize_cmp_roles(["member"]) == frozenset({"member"})
    assert normalize_cmp_roles(["member:signature"]) == frozenset({"member"})


def test_normalize_cmp_roles_ignores_unknown_roles() -> None:
    assert normalize_cmp_roles(["viewer", "admin:admin"]) == frozenset({"admin"})


def test_extract_cmp_roles_reads_resource_access_client_roles() -> None:
    claims = {
        "sub": "user-1",
        "resource_access": {
            "cmp": {"roles": ["member:signature", "other-client-role"]},
            "other": {"roles": ["admin"]},
        },
    }
    assert extract_cmp_roles(claims, "cmp") == frozenset({"member"})


def test_admin_does_not_inherit_member_access() -> None:
    roles = normalize_cmp_roles(["admin"])
    assert has_admin_access(roles) is True
    assert has_member_access(roles) is False


def test_member_cannot_access_admin_routes() -> None:
    roles = normalize_cmp_roles(["member:signature"])
    assert has_member_access(roles) is True
    assert has_admin_access(roles) is False


def test_principal_exposes_canonical_roles_only() -> None:
    principal = AuthenticatedPrincipal.from_claims(
        {
            "sub": "user-1",
            "resource_access": {"cmp": {"roles": ["admin:admin"]}},
        },
        client_id="cmp",
    )
    assert principal.roles == frozenset({"admin"})
    assert principal.is_admin() is True
    assert principal.can_access_member_routes() is False
