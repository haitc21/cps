import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cps.api.dependencies import get_uow
from cps.api.errors import register_error_handlers
from cps.api.routers import operations as flavor_router
from cps.api.routers.operations import create_flavor
from cps.api.schemas.flavor import (
    FlavorAccessReplaceBody,
    FlavorCreateBody,
    FlavorExtraSpecsPatchBody,
)
from cps.api.schemas.operations import OperationView
from cps.contracts.errors import InvalidRequestError
from cps.infrastructure.db.models.enums import OperationState
from cps.main import create_app
from cps.observability.middleware import CorrelationIdMiddleware
from cps.security.auth.middleware import KeycloakAuthMiddleware
from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.verifier import KeycloakJwtVerifier


def test_admin_openapi_exposes_explicit_flavor_mutations_only():
    paths = create_app().openapi()["paths"]
    base = "/api/v1/admin/provider-connections/{connection_id}/flavors"
    assert "post" in paths[base]
    assert "delete" in paths[f"{base}/{{flavor_id}}"]
    assert "put" in paths[f"{base}/{{flavor_id}}/access"]
    assert "patch" in paths[f"{base}/{{flavor_id}}/extra-specs"]
    assert "patch" not in paths[f"{base}/{{flavor_id}}"]
    assert "immutable" in paths[base]["post"]["description"].lower()
    assert "/api/v1/provider-connections/{connection_id}/flavors" not in paths


@pytest.mark.asyncio
async def test_create_requires_idempotency_header_before_uow_mutation():
    uow = SimpleNamespace(commit=None)
    with pytest.raises(InvalidRequestError):
        await create_flavor(
            uuid.uuid4(),
            FlavorCreateBody(
                name="small",
                vcpus=1,
                ram_mib=512,
                root_disk_gib=0,
                is_public=True,
            ),
            SimpleNamespace(state=SimpleNamespace(correlation_id=str(uuid.uuid4()))),
            None,
            uow,
        )


@pytest.mark.asyncio
async def test_all_four_admin_routes_map_body_commit_and_return_202(monkeypatch):
    connection_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    operation = OperationView(
        id=operation_id,
        provider_connection_id=connection_id,
        operation_type="openstack.flavor.create",
        state=OperationState.QUEUED,
        progress_percent=None,
        request_payload={},
        result_payload=None,
        error_payload=None,
        correlation_id=uuid.uuid4(),
        causation_id=None,
        actor_context=None,
        provider_request_id=None,
        version=2,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service = SimpleNamespace(create_flavor_operation=AsyncMock(return_value=operation))
    monkeypatch.setattr(flavor_router, "_service", lambda _uow: service)
    uow = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(state=SimpleNamespace(correlation_id=str(uuid.uuid4())))
    calls = [
        (
            flavor_router.create_flavor,
            (
                connection_id,
                FlavorCreateBody(
                    name="small", vcpus=1, ram_mib=512, root_disk_gib=0, is_public=True
                ),
                request,
                "create-key",
                uow,
            ),
            "create",
        ),
        (
            flavor_router.delete_flavor,
            (connection_id, "flavor-1", request, "delete-key", uow),
            "delete",
        ),
        (
            flavor_router.replace_flavor_access,
            (
                connection_id,
                "flavor-1",
                FlavorAccessReplaceBody(project_provider_resource_ids=["project-1"]),
                request,
                "access-key",
                uow,
            ),
            "access.replace",
        ),
        (
            flavor_router.patch_flavor_extra_specs,
            (
                connection_id,
                "flavor-1",
                FlavorExtraSpecsPatchBody(set={"hw:cpu_policy": "shared"}),
                request,
                "spec-key",
                uow,
            ),
            "extra_specs.patch",
        ),
    ]
    for endpoint, args, expected_operation in calls:
        response = await endpoint(*args)
        assert response.status_code == 202
        typed = service.create_flavor_operation.await_args.kwargs["request"]
        assert typed.operation == expected_operation
    assert uow.commit.await_count == 4


def _authenticated_flavor_app(monkeypatch):
    operation = OperationView(
        id=uuid.uuid4(),
        provider_connection_id=uuid.uuid4(),
        operation_type="openstack.flavor.create",
        state=OperationState.QUEUED,
        progress_percent=None,
        request_payload={},
        result_payload=None,
        error_payload=None,
        correlation_id=uuid.uuid4(),
        causation_id=None,
        actor_context=None,
        provider_request_id=None,
        version=2,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    operation_call = AsyncMock(return_value=operation)
    monkeypatch.setattr(
        flavor_router.OperationApplicationService,
        "create_flavor_operation",
        operation_call,
    )
    uow = SimpleNamespace(
        operations=object(), outbox=object(), inventory=object(), commit=AsyncMock()
    )
    entered = AsyncMock()

    async def uow_override():
        await entered()
        yield uow

    app = FastAPI()
    app.include_router(flavor_router.admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_uow] = uow_override
    register_error_handlers(app)
    verifier = KeycloakJwtVerifier.from_settings(
        issuer="http://127.0.0.1:8080/realms/test",
        client_id="cmp",
        audience=None,
        jwks_cache_ttl_seconds=300,
    )

    async def verify(value):
        role = "admin" if value == "administrator" else "member"
        return AuthenticatedPrincipal(subject=value, roles=frozenset({role}), client_id="cmp")

    verifier.verify = AsyncMock(side_effect=verify)  # type: ignore[method-assign]
    app.add_middleware(KeycloakAuthMiddleware, verifier=verifier)
    app.add_middleware(CorrelationIdMiddleware)
    return TestClient(app, raise_server_exceptions=False), operation_call, uow, entered


@pytest.mark.parametrize(
    "method,suffix,payload",
    [
        (
            "post",
            "",
            {"name": "small", "vcpus": 1, "ram_mib": 512, "root_disk_gib": 0, "is_public": True},
        ),
        ("delete", "/flavor-1", None),
        ("put", "/flavor-1/access", {"project_provider_resource_ids": ["project-1"]}),
        ("patch", "/flavor-1/extra-specs", {"set": {"hw:cpu_policy": "shared"}}),
    ],
)
def test_asgi_flavor_routes_admin_accepted_member_denied_before_uow(
    monkeypatch, method, suffix, payload
):
    client, operation_call, uow, entered = _authenticated_flavor_app(monkeypatch)
    base = f"/api/v1/admin/provider-connections/{uuid.uuid4()}/flavors{suffix}"
    member = client.request(
        method,
        base,
        json=payload,
        headers={"Authorization": "Bearer regular-member", "Idempotency-Key": "key"},
    )
    assert member.status_code == 403
    assert member.json()["errorCode"] == "FORBIDDEN"
    operation_call.assert_not_awaited()
    uow.commit.assert_not_awaited()
    entered.assert_not_awaited()

    admin = client.request(
        method,
        base,
        json=payload,
        headers={"Authorization": "Bearer administrator", "Idempotency-Key": "key"},
    )
    assert admin.status_code == 202
    operation_call.assert_awaited_once()
    uow.commit.assert_awaited_once()


def test_asgi_missing_idempotency_error_is_normalized_without_service_mutation(monkeypatch):
    client, operation_call, uow, _entered = _authenticated_flavor_app(monkeypatch)
    response = client.post(
        f"/api/v1/admin/provider-connections/{uuid.uuid4()}/flavors",
        json={"name": "small", "vcpus": 1, "ram_mib": 512, "root_disk_gib": 0, "is_public": True},
        headers={"Authorization": "Bearer administrator"},
    )
    assert response.status_code == 400
    assert response.json()["errorCode"] == "VALIDATION_FAILED"
    operation_call.assert_not_awaited()
    uow.commit.assert_not_awaited()
