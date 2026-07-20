"""CPS-003: readiness against local Compose infrastructure."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from cps.config import Settings
from cps.main import create_app

pytestmark = pytest.mark.integration


def _compose_available() -> bool:
    return os.getenv("CPS_RUN_INTEGRATION", "0") == "1"


@pytest.mark.skipif(not _compose_available(), reason="integration disabled")
def test_readiness_succeeds_against_local_compose() -> None:
    settings = Settings(
        environment="test",
        database_url=os.getenv(
            "CPS_DATABASE_URL",
            "postgresql+psycopg://cps:cps_dev_password@127.0.0.1:5432/cps",
        ),
        rabbitmq_url=os.getenv(
            "CPS_RABBITMQ_URL",
            "amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp",
        ),
        _env_file=None,
    )
    client = TestClient(create_app(settings=settings))

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ok"
    assert "valkey" not in body["checks"]
