"""CPS-002: correlation ID middleware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cps.main import create_app


def test_correlation_id_generated_when_missing() -> None:
    app = create_app()

    @app.get("/_test/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/_test/ping")
    assert response.status_code == 200
    assert "x-correlation-id" in response.headers
    assert response.headers["x-correlation-id"]


def test_correlation_id_accepted_from_request() -> None:
    app = create_app()

    @app.get("/_test/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/_test/ping", headers={"X-Correlation-ID": "client-corr-1"})
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "client-corr-1"
