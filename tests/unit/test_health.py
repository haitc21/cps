"""CPS-003: health endpoint unit behavior."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from cps.config import Settings
from cps.main import create_app


class _FakeChecks:
    def __init__(self, database_ok: bool = True, rabbitmq_ok: bool = True) -> None:
        self.database_ok = database_ok
        self.rabbitmq_ok = rabbitmq_ok
        self.called: list[str] = []

    async def check_database(self) -> dict[str, Any]:
        self.called.append("database")
        return {"status": "up" if self.database_ok else "down"}

    async def check_rabbitmq(self) -> dict[str, Any]:
        self.called.append("rabbitmq")
        return {"status": "up" if self.rabbitmq_ok else "down"}


def test_liveness_is_process_only() -> None:
    settings = Settings(environment="test", _env_file=None)
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_dependencies_up() -> None:
    settings = Settings(environment="test", _env_file=None)
    app = create_app(settings=settings)
    app.state.health_checks = _FakeChecks(database_ok=True, rabbitmq_ok=True)
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "up"
    assert body["checks"]["rabbitmq"]["status"] == "up"
    assert "valkey" not in body["checks"]


def test_readiness_fails_when_database_down() -> None:
    settings = Settings(environment="test", _env_file=None)
    app = create_app(settings=settings)
    app.state.health_checks = _FakeChecks(database_ok=False, rabbitmq_ok=True)
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["checks"]["database"]["status"] == "down"


def test_readiness_fails_when_rabbitmq_down() -> None:
    settings = Settings(environment="test", _env_file=None)
    app = create_app(settings=settings)
    app.state.health_checks = _FakeChecks(database_ok=True, rabbitmq_ok=False)
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["rabbitmq"]["status"] == "down"
