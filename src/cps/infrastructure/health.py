"""Dependency health checks for readiness probes."""

from __future__ import annotations

import asyncio
from typing import Any

import aio_pika
import psycopg

from cps.config import Settings
from cps.infrastructure.db import to_psycopg_conninfo


class HealthChecks:
    """Probe PostgreSQL and RabbitMQ connectivity."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def check_database(self) -> dict[str, Any]:
        conninfo = to_psycopg_conninfo(self._settings.require_database_url)

        def _probe() -> None:
            with psycopg.connect(conninfo, connect_timeout=5) as connection:
                connection.execute("SELECT 1")

        try:
            await asyncio.to_thread(_probe)
            return {"status": "up"}
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            return {"status": "down", "message": type(exc).__name__}

    async def check_rabbitmq(self) -> dict[str, Any]:
        try:
            connection = await aio_pika.connect_robust(
                self._settings.require_rabbitmq_url,
                timeout=5,
            )
            await connection.close()
            return {"status": "up"}
        except Exception as exc:  # noqa: BLE001 - readiness must never raise
            return {"status": "down", "message": type(exc).__name__}
