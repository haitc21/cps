"""Integration tests against the local Keycloak stack."""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cps.config import Settings
from cps.observability.middleware import CorrelationIdMiddleware
from cps.security.auth.middleware import KeycloakAuthMiddleware, create_keycloak_verifier

KEYCLOAK_URL = os.getenv("CPS_TEST_KEYCLOAK_URL", "http://127.0.0.1:8080")
KEYCLOAK_REALM = os.getenv("CPS_TEST_KEYCLOAK_REALM", "vnpost")
KEYCLOAK_CLIENT_ID = os.getenv("CPS_TEST_KEYCLOAK_CLIENT_ID", "cmp")
ADMIN_USER = os.getenv("CPS_TEST_KEYCLOAK_ADMIN_USER", "admin@vnpost.vn")
ADMIN_PASSWORD = os.getenv(  # pragma: allowlist secret
    "CPS_TEST_KEYCLOAK_ADMIN_PASSWORD",
    "Vnpost@1",
)
MEMBER_USER = os.getenv("CPS_TEST_KEYCLOAK_MEMBER_USER", "member@vnpost.vn")
MEMBER_PASSWORD = os.getenv(  # pragma: allowlist secret
    "CPS_TEST_KEYCLOAK_MEMBER_PASSWORD",
    "Vnpost@1",
)


def _integration_enabled() -> bool:
    return os.getenv("CPS_RUN_INTEGRATION") == "1"


def _require_keycloak() -> None:
    if not _integration_enabled():
        pytest.skip("integration disabled; set CPS_RUN_INTEGRATION=1")
    try:
        response = httpx.get(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}", timeout=2.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"Keycloak unavailable: {exc}")


def _fetch_token(username: str, password: str) -> str:
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    response = httpx.post(
        token_url,
        data={
            "grant_type": "password",
            "client_id": KEYCLOAK_CLIENT_ID,
            "username": username,
            "password": password,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        msg = "token response missing access_token"
        raise RuntimeError(msg)
    return access_token


def _auth_settings() -> Settings:
    return Settings(
        environment="test",
        _env_file=None,
        keycloak_auth_enabled=True,
        keycloak_url=KEYCLOAK_URL,
        keycloak_realm=KEYCLOAK_REALM,
        keycloak_client_id=KEYCLOAK_CLIENT_ID,
        keycloak_issuer_override=f"{KEYCLOAK_URL.rstrip('/')}/realms/{KEYCLOAK_REALM}",
    )


def _integration_client(settings: Settings) -> TestClient:
    verifier = create_keycloak_verifier(settings)
    assert verifier is not None
    app = FastAPI()
    app.state.settings = settings
    app.add_middleware(
        KeycloakAuthMiddleware,
        settings=settings,
        verifier=verifier,
    )
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/api/v1/member-probe")
    async def member_probe() -> dict[str, str]:
        return {"scope": "member"}

    @app.get("/api/v1/admin/admin-probe")
    async def admin_probe() -> dict[str, str]:
        return {"scope": "admin"}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.integration
def test_admin_token_can_call_member_api() -> None:
    _require_keycloak()
    token = _fetch_token(ADMIN_USER, ADMIN_PASSWORD)
    client = _integration_client(_auth_settings())

    response = client.get("/api/v1/member-probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert token not in response.text


@pytest.mark.integration
def test_member_token_is_rejected_for_admin_api() -> None:
    _require_keycloak()
    token = _fetch_token(MEMBER_USER, MEMBER_PASSWORD)
    client = _integration_client(_auth_settings())

    response = client.get("/api/v1/admin/admin-probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZATION_FAILED"


@pytest.mark.integration
def test_member_token_can_call_member_api() -> None:
    _require_keycloak()
    token = _fetch_token(MEMBER_USER, MEMBER_PASSWORD)
    client = _integration_client(_auth_settings())

    response = client.get("/api/v1/member-probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
