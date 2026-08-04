"""OpenAPI route normalization contract tests."""

from __future__ import annotations

from cps.api.prefixes import ADMIN_API_PREFIX, MEMBER_API_PREFIX
from cps.main import create_app
from cps.security.auth.middleware import ORG_SCOPE_HEADER, WS_SCOPE_HEADER

_ADMIN_PATHS = frozenset(
    {
        f"{ADMIN_API_PREFIX}/providers",
        f"{ADMIN_API_PREFIX}/providers/{{provider_id}}",
        f"{ADMIN_API_PREFIX}/providers/{{provider_id}}/identity-domains",
        f"{ADMIN_API_PREFIX}/providers/{{provider_id}}/identity-projects",
        f"{ADMIN_API_PREFIX}/providers/{{provider_id}}/connections",
        f"{ADMIN_API_PREFIX}/provider-connections",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/catalog",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/validate",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/inventory-syncs",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/inventory-refreshes",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/{{resource_type}}/{{action}}",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/role-assignments",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/quotas",
        f"{ADMIN_API_PREFIX}/provider-connections/{{connection_id}}/flavors",
        f"{ADMIN_API_PREFIX}/operations",
        f"{ADMIN_API_PREFIX}/operations/{{operation_id}}",
        f"{ADMIN_API_PREFIX}/operations/{{operation_id}}/events",
        f"{ADMIN_API_PREFIX}/operations/{{operation_id}}/audit",
    }
)

_MEMBER_PATHS = frozenset(
    {
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/capabilities",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/network-operations",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/volumes",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/volume-snapshots",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/keypairs",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/volume-attachments",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/instances",
        (
            f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/"
            "instances/{instance_provider_resource_id}/{action}"
        ),
        f"{MEMBER_API_PREFIX}/operations",
        f"{MEMBER_API_PREFIX}/operations/{{operation_id}}",
        f"{MEMBER_API_PREFIX}/operations/{{operation_id}}/events",
        f"{MEMBER_API_PREFIX}/operations/{{operation_id}}/audit",
        f"{MEMBER_API_PREFIX}/{{resource_type}}",
        f"{MEMBER_API_PREFIX}/{{resource_type}}/{{resource_id}}",
    }
)

_LEGACY_ADMIN_ON_MEMBER_PREFIX = frozenset(
    {
        f"{MEMBER_API_PREFIX}/providers",
        f"{MEMBER_API_PREFIX}/provider-connections",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/validate",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/inventory-syncs",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/role-assignments",
        f"{MEMBER_API_PREFIX}/provider-connections/{{connection_id}}/quotas",
    }
)


def test_openapi_paths_use_normalized_admin_and_member_surfaces() -> None:
    paths = set(create_app().openapi()["paths"])

    assert _ADMIN_PATHS <= paths
    assert _MEMBER_PATHS <= paths
    assert _LEGACY_ADMIN_ON_MEMBER_PREFIX.isdisjoint(paths)


def test_admin_and_member_surfaces_do_not_overlap() -> None:
    paths = set(create_app().openapi()["paths"])
    admin_paths = {path for path in paths if path.startswith(f"{ADMIN_API_PREFIX}/")}
    member_paths = {
        path
        for path in paths
        if path.startswith(f"{MEMBER_API_PREFIX}/") and not path.startswith(f"{ADMIN_API_PREFIX}/")
    }

    assert admin_paths.isdisjoint(member_paths)


def test_openapi_tags_identify_admin_and_member_surfaces() -> None:
    paths = create_app().openapi()["paths"]

    assert paths["/api/v1/admin/providers"]["get"]["tags"] == ["Admin Providers"]
    assert paths["/api/v1/operations"]["get"]["tags"] == ["Operations"]
    assert paths["/api/v1/admin/operations"]["get"]["tags"] == ["Admin Operations"]
    assert paths["/api/v1/{resource_type}"]["get"]["tags"] == ["Inventory"]


def _header_names(operation: dict[str, object]) -> set[str]:
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list):
        return set()
    names: set[str] = set()
    for parameter in parameters:
        if isinstance(parameter, dict) and parameter.get("in") == "header":
            name = parameter.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def test_member_openapi_operations_declare_scope_headers() -> None:
    paths = create_app().openapi()["paths"]
    member_operations = [
        operation
        for path, operations in paths.items()
        if path.startswith(f"{MEMBER_API_PREFIX}/") and not path.startswith(f"{ADMIN_API_PREFIX}/")
        for operation in operations.values()
        if isinstance(operation, dict)
    ]

    assert member_operations
    for operation in member_operations:
        headers = _header_names(operation)
        assert ORG_SCOPE_HEADER in headers
        assert WS_SCOPE_HEADER in headers


def test_admin_openapi_operations_do_not_declare_scope_headers() -> None:
    paths = create_app().openapi()["paths"]
    admin_operations = [
        operation
        for path, operations in paths.items()
        if path.startswith(f"{ADMIN_API_PREFIX}/")
        for operation in operations.values()
        if isinstance(operation, dict)
    ]

    assert admin_operations
    for operation in admin_operations:
        headers = _header_names(operation)
        assert ORG_SCOPE_HEADER not in headers
        assert WS_SCOPE_HEADER not in headers
