"""API error handlers must return the CMP/BMS BaseResponse envelope."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cps.config import Settings
from cps.contracts.errors import (
    AuthenticationError,
    AuthorizationError,
    CapabilityUnsupportedError,
    DomainConflictError,
    OperationTimeoutError,
    ProviderOperationError,
    ResourceNotFoundError,
)
from cps.main import create_app


@pytest.mark.parametrize(
    ("exc", "status_code", "error_code"),
    (
        (ResourceNotFoundError("missing"), 404, "NOT_FOUND"),
        (DomainConflictError("conflict"), 409, "CONFLICT"),
        (CapabilityUnsupportedError("unsupported"), 422, "CAPABILITY_001"),
        (ProviderOperationError(cause="provider failed"), 502, "EXTERNAL_SERVICE_ERROR"),
        (OperationTimeoutError("timed out"), 504, "EXTERNAL_SERVICE_ERROR"),
        (AuthenticationError(), 401, "UNAUTHORIZED"),
        (AuthorizationError(), 403, "FORBIDDEN"),
    ),
)
def test_domain_errors_use_common_envelope(
    exc: Exception,
    status_code: int,
    error_code: str,
) -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_test/error")
    async def raise_error() -> None:
        raise exc

    response = TestClient(app, raise_server_exceptions=False).get("/_test/error")
    body = response.json()
    assert response.status_code == status_code
    assert body["statusCode"] == status_code
    assert body["errorCode"] == error_code
    assert "error" not in body
    assert response.headers["x-correlation-id"]


def test_validation_and_internal_errors_use_common_envelope() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_test/validation")
    async def validation(value: int) -> dict[str, int]:
        return {"value": value}

    @app.get("/_test/internal")
    async def internal() -> None:
        raise RuntimeError("unsafe internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    invalid = client.get("/_test/validation")
    internal_response = client.get("/_test/internal")
    assert invalid.status_code == 400
    assert invalid.json()["errorCode"] == "VALIDATION_FAILED"
    assert "fields" in invalid.json()["data"]
    assert (internal_response.status_code, internal_response.json()["errorCode"]) == (
        500,
        "INTERNAL_ERROR",
    )
    assert "unsafe internal detail" not in internal_response.text


def test_provider_error_does_not_leak_secret_from_cause() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    secret = "password=super-secret-token"  # pragma: allowlist secret

    @app.get("/_test/provider-secret")
    async def raise_provider_secret() -> None:
        raise ProviderOperationError(
            cause=f"{secret} Authorization: Bearer leaked"  # pragma: allowlist secret
        )

    response = TestClient(app, raise_server_exceptions=False).get("/_test/provider-secret")
    assert response.status_code == 502
    body = response.text
    assert response.json()["message"] == "Provider operation failed"
    assert secret not in body
    assert "Bearer leaked" not in body  # pragma: allowlist secret
    assert "Authorization" not in body


def test_provider_error_ignores_positional_secret_as_public_message() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    leaked = "password=leaked Authorization: Bearer token"  # pragma: allowlist secret

    @app.get("/_test/provider-positional")
    async def raise_provider_positional() -> None:
        raise ProviderOperationError(leaked)

    response = TestClient(app, raise_server_exceptions=False).get("/_test/provider-positional")
    assert response.status_code == 502
    assert response.json()["message"] == "Provider operation failed"
    assert leaked not in response.text
    assert "password=leaked" not in response.text  # pragma: allowlist secret
    assert "Bearer token" not in response.text  # pragma: allowlist secret


def test_success_envelope_shape() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_test/success")
    async def success():
        from cps.api.response import api_success

        return api_success({"ok": True})

    response = TestClient(app, raise_server_exceptions=False).get("/_test/success")
    body = response.json()
    assert body["statusCode"] == 200
    assert body.get("errorCode") is None
    assert body["message"] == "Success"
    assert body["data"] == {"ok": True}
    assert "timestamp" in body
