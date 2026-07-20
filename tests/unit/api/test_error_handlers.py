"""API error handlers must return the common error envelope."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cps.config import Settings
from cps.contracts.errors import (
    CapabilityUnsupportedError,
    DomainConflictError,
    OperationTimeoutError,
    ProviderOperationError,
    ResourceNotFoundError,
)
from cps.main import create_app


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    (
        (ResourceNotFoundError("missing"), 404, "NOT_FOUND"),
        (DomainConflictError("conflict"), 409, "CONFLICT"),
        (CapabilityUnsupportedError("unsupported"), 422, "CAPABILITY_UNSUPPORTED"),
        (ProviderOperationError(cause="provider failed"), 502, "PROVIDER_ERROR"),
        (OperationTimeoutError("timed out"), 504, "OPERATION_TIMEOUT"),
    ),
)
def test_domain_errors_use_common_envelope(exc: Exception, status_code: int, code: str) -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_test/error")
    async def raise_error() -> None:
        raise exc

    response = TestClient(app, raise_server_exceptions=False).get("/_test/error")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
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
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "INVALID_REQUEST")
    assert (internal_response.status_code, internal_response.json()["error"]["code"]) == (
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
    assert response.json()["error"]["message"] == "Provider operation failed"
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
    assert response.json()["error"]["message"] == "Provider operation failed"
    assert leaked not in response.text
    assert "password=leaked" not in response.text  # pragma: allowlist secret
    assert "Bearer token" not in response.text  # pragma: allowlist secret
