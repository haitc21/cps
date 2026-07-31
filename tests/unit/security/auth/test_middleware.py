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


def _auth_settings(**overrides: object) -> Settings:
    base = {
        "environment": "test",
        "_env_file": None,
        "keycloak_issuer_override": "http://127.0.0.1:8080/realms/vnpost",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def _verify_side_effect(token: str) -> AuthenticatedPrincipal:
    if token == "admin-token":
        return AuthenticatedPrincipal(
            subject="admin-user",
            roles=frozenset({"admin"}),
            client_id="cmp",
        )
    if token == "member-token":
        return AuthenticatedPrincipal(
            subject="member-user",
            roles=frozenset({"member"}),
            client_id="cmp",
        )
    raise JwtVerificationError("invalid token")


def _minimal_auth_app(settings: Settings) -> tuple[FastAPI, KeycloakJwtVerifier]:
    verifier = KeycloakJwtVerifier.from_settings(
        issuer=settings.keycloak_issuer,
        client_id=settings.keycloak_client_id,
        audience=settings.keycloak_audience,
        jwks_cache_ttl_seconds=settings.keycloak_jwks_cache_ttl_seconds,
    )
    verifier.verify = AsyncMock(side_effect=_verify_side_effect)  # type: ignore[method-assign]

    app = FastAPI()
    app.state.settings = settings
    app.add_middleware(
        KeycloakAuthMiddleware,
        verifier=verifier,
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

    return app, verifier


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
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
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
    headers = {"Authorization": "Bearer member-token"}

    member_response = client.get("/api/v1/member-probe", headers=headers)
    admin_response = client.get("/api/v1/admin/admin-probe", headers=headers)

    assert member_response.status_code == 200
    assert admin_response.status_code == 403
    assert admin_response.json()["error"]["code"] == "AUTHORIZATION_FAILED"


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
