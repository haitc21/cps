"""Authentication middleware and route policy tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cps.config import Settings
from cps.main import create_app
from cps.observability.middleware import CorrelationIdMiddleware
from cps.security.auth.middleware import KeycloakAuthMiddleware
from cps.security.auth.principal import AuthenticatedPrincipal
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

# Deterministic synthetic ObjectIds from provider-tenancy authorization design.
TEST_ORG_ID = "64b000000000000000000001"
TEST_WS_ID = "64b000000000000000000101"


def _auth_settings(**overrides: object) -> Settings:
    base = {
        "environment": "test",
        "_env_file": None,
        "keycloak_issuer_override": "http://127.0.0.1:8080/realms/vnpost",
        "app_owner": "admin@vnpost.vn",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def _verify_side_effect(token: str) -> AuthenticatedPrincipal:
    if token == "admin-token":
        return AuthenticatedPrincipal(
            subject="admin-user",
            roles=frozenset({"admin"}),
            client_roles=frozenset({"admin:admin"}),
            client_id="cmp",
        )
    if token == "member-token":
        return AuthenticatedPrincipal(
            subject="member-user",
            roles=frozenset({"member"}),
            client_roles=frozenset({"member"}),
            client_id="cmp",
        )
    if token == "owner-token":
        return AuthenticatedPrincipal(
            subject="owner-user",
            roles=frozenset(),
            client_roles=frozenset(),
            client_id="cmp",
            preferred_username="admin@vnpost.vn",
            email="admin@vnpost.vn",
        )
    raise JwtVerificationError("invalid token")


def _minimal_auth_app(
    settings: Settings,
    *,
    tms_authorizer: AsyncMock | None = None,
) -> tuple[FastAPI, KeycloakJwtVerifier, AsyncMock]:
    verifier = KeycloakJwtVerifier.from_settings(
        issuer=settings.keycloak_issuer,
        client_id=settings.keycloak_client_id,
        audience=settings.keycloak_audience,
        jwks_cache_ttl_seconds=settings.keycloak_jwks_cache_ttl_seconds,
    )
    verifier.verify = AsyncMock(side_effect=_verify_side_effect)  # type: ignore[method-assign]

    app = FastAPI()
    app.state.settings = settings
    authorizer = tms_authorizer or AsyncMock(return_value=True)
    app.add_middleware(
        KeycloakAuthMiddleware,
        verifier=verifier,
        tms_authorizer=authorizer,
        app_owner=settings.app_owner,
    )
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/member-probe")
    async def member_probe() -> dict[str, str]:
        return {"scope": "member"}

    @app.get("/api/v1/admin/admin-probe")
    async def admin_probe() -> dict[str, str]:
        return {"scope": "admin"}

    return app, verifier, authorizer


def _scope_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Org-ID": TEST_ORG_ID,
        "X-WS-ID": TEST_WS_ID,
    }


def test_public_health_endpoints_do_not_require_auth() -> None:
    settings = _auth_settings()
    client = TestClient(create_app(settings), raise_server_exceptions=False)

    live = client.get("/health/live")
    ready = client.get("/health/ready")
    metrics = client.get("/metrics")

    assert live.status_code == 200
    assert ready.status_code in {200, 503}
    assert metrics.status_code == 200


def test_missing_token_returns_401_on_protected_route() -> None:
    client = TestClient(_minimal_auth_app(_auth_settings())[0], raise_server_exceptions=False)

    response = client.get("/api/v1/member-probe")

    assert response.status_code == 401
    assert response.json()["errorCode"] == "UNAUTHORIZED"
    assert "Bearer" not in response.text


def test_invalid_token_returns_401_without_leaking_token() -> None:
    client = TestClient(_minimal_auth_app(_auth_settings())[0], raise_server_exceptions=False)
    secret_token = "super-secret-access-token-value"  # pragma: allowlist secret

    response = client.get(
        "/api/v1/member-probe",
        headers={"Authorization": f"Bearer {secret_token}"},
    )

    assert response.status_code == 401
    assert secret_token not in response.text


def test_admin_token_can_access_admin_but_not_member_routes() -> None:
    client = TestClient(_minimal_auth_app(_auth_settings())[0], raise_server_exceptions=False)
    headers = {"Authorization": "Bearer admin-token"}

    member_response = client.get("/api/v1/member-probe", headers=headers)
    admin_response = client.get("/api/v1/admin/admin-probe", headers=headers)

    assert member_response.status_code == 403
    assert admin_response.status_code == 200


def test_member_token_can_access_member_but_not_admin_routes() -> None:
    client = TestClient(_minimal_auth_app(_auth_settings())[0], raise_server_exceptions=False)
    headers = _scope_headers("member-token")

    member_response = client.get("/api/v1/member-probe", headers=headers)
    admin_response = client.get("/api/v1/admin/admin-probe", headers=headers)

    assert member_response.status_code == 200
    assert admin_response.status_code == 403
    assert admin_response.json()["errorCode"] == "FORBIDDEN"


def test_app_owner_bypasses_route_role_and_tms_scope_checks_after_authentication() -> None:
    app, _verifier, authorizer = _minimal_auth_app(_auth_settings())
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer owner-token"}

    member_response = client.get("/api/v1/member-probe", headers=headers)
    admin_response = client.get("/api/v1/admin/admin-probe", headers=headers)

    assert member_response.status_code == 200
    assert admin_response.status_code == 200
    authorizer.assert_not_awaited()


def test_require_admin_allows_configured_app_owner_without_admin_role() -> None:
    from fastapi import Depends

    from cps.security.auth.middleware import require_admin

    app, _verifier, _authorizer = _minimal_auth_app(_auth_settings())

    @app.get("/api/v1/admin/owner-probe", dependencies=[Depends(require_admin)])
    async def owner_admin_probe() -> dict[str, str]:
        return {"scope": "admin-owner"}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/api/v1/admin/owner-probe",
        headers={"Authorization": "Bearer owner-token"},
    )

    assert response.status_code == 200


def test_member_route_requires_both_scope_headers() -> None:
    app, _verifier, authorizer = _minimal_auth_app(_auth_settings())
    client = TestClient(app, raise_server_exceptions=False)

    missing_both = client.get(
        "/api/v1/member-probe",
        headers={"Authorization": "Bearer member-token"},
    )
    missing_workspace = client.get(
        "/api/v1/member-probe",
        headers={
            "Authorization": "Bearer member-token",
            "X-Org-ID": TEST_ORG_ID,
        },
    )

    assert missing_both.status_code == 403
    assert missing_workspace.status_code == 403
    authorizer.assert_not_awaited()


def test_member_route_forwards_verified_subject_token_and_scope_to_tms() -> None:
    authorizer = AsyncMock(return_value=True)
    app, _verifier, _authorizer = _minimal_auth_app(
        _auth_settings(),
        tms_authorizer=authorizer,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/member-probe", headers=_scope_headers("member-token"))

    assert response.status_code == 200
    authorizer.assert_awaited_once_with(
        bearer_token="member-token",
        subject="member-user",
        org_id=TEST_ORG_ID,
        workspace_id=TEST_WS_ID,
    )


def test_tms_denial_blocks_member_handler() -> None:
    authorizer = AsyncMock(return_value=False)
    app, _verifier, _authorizer = _minimal_auth_app(
        _auth_settings(),
        tms_authorizer=authorizer,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/member-probe", headers=_scope_headers("member-token"))

    assert response.status_code == 403
    assert response.json()["errorCode"] == "FORBIDDEN"


def test_tms_unavailable_blocks_member_handler_without_leaking_token() -> None:
    from cps.security.auth.tms import TmsAuthorizationUnavailable

    secret_token = "member-token"  # pragma: allowlist secret
    authorizer = AsyncMock(side_effect=TmsAuthorizationUnavailable())
    app, _verifier, _authorizer = _minimal_auth_app(
        _auth_settings(),
        tms_authorizer=authorizer,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/member-probe", headers=_scope_headers(secret_token))

    assert response.status_code == 503
    assert secret_token not in response.text


def test_required_access_for_path_policy() -> None:
    from cps.security.auth.middleware import is_public_path, required_access_for_path

    assert is_public_path("/health/live") is True
    assert is_public_path("/metrics") is True
    assert required_access_for_path("/api/v1/operations") == "member"
    assert required_access_for_path("/api/v1/admin/providers") == "admin"
    assert required_access_for_path("/api/v1/admin/operations") == "admin"
    assert required_access_for_path("/api/v1/administered") == "member"
    assert required_access_for_path("/api/v10/providers") is None
    assert required_access_for_path("/internal/v1/providers/x/resolution") is None
