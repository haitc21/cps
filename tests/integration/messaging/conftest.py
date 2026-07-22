"""Reuse guarded disposable PostgreSQL fixtures for messaging integration."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import aio_pika
import pytest
import pytest_asyncio

from cps.infrastructure.messaging.topology import DeclaredEventTopology, EventTopologyBuilder
from tests.integration.db.conftest import (
    db_admin_conn,
    db_engine,
    db_session_factory,
    db_tx,
    disposable_database_manager,
    fresh_migrated_database,
    integration_database_url,
    integration_template_database_url,
    migrated_database,
    template_database_conn,
    template_schema_snapshot,
)
from tests.integration.messaging.disposable_vhost import DisposableVhostManager

INTEGRATION_RETRY_TTLS_MS = (5_000, 5_000)

__all__ = [
    "db_admin_conn",
    "db_engine",
    "db_session_factory",
    "db_tx",
    "disposable_database_manager",
    "fresh_migrated_database",
    "integration_database_url",
    "integration_database_url",
    "integration_template_database_url",
    "migrated_database",
    "template_database_conn",
    "template_schema_snapshot",
]


def require_rabbitmq_base_url() -> str:
    if os.getenv("CPS_RUN_INTEGRATION", "0") != "1":
        pytest.skip("integration disabled; set CPS_RUN_INTEGRATION=1")
    value = os.getenv("CPS_TEST_RABBITMQ_URL")
    if not value:
        pytest.fail("CPS_TEST_RABBITMQ_URL is required when CPS_RUN_INTEGRATION=1")
    return value


@pytest.fixture(scope="session")
def rabbitmq_base_url() -> str:
    return require_rabbitmq_base_url()


@pytest.fixture(scope="session")
def rabbitmq_management_url() -> str:
    return os.getenv(
        "CPS_RABBITMQ_MANAGEMENT_URL",
        "http://127.0.0.1:15672",
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def disposable_vhost_manager(
    rabbitmq_base_url: str,
    rabbitmq_management_url: str,
) -> AsyncIterator[DisposableVhostManager]:
    manager = DisposableVhostManager(
        base_amqp_url=rabbitmq_base_url,
        management_url=rabbitmq_management_url,
    )
    await manager.setup()
    try:
        yield manager
    finally:
        await manager.teardown()


@pytest_asyncio.fixture
async def rabbitmq_connection(
    disposable_vhost_manager: DisposableVhostManager,
) -> AsyncIterator[aio_pika.abc.AbstractRobustConnection]:
    connection = await aio_pika.connect_robust(
        disposable_vhost_manager.integration_url,
        timeout=5,
        heartbeat=30,
    )
    try:
        yield connection
    finally:
        await connection.close()


@pytest_asyncio.fixture
async def rabbitmq_channel(
    rabbitmq_connection: aio_pika.abc.AbstractRobustConnection,
) -> AsyncIterator[aio_pika.abc.AbstractChannel]:
    channel = await rabbitmq_connection.channel(on_return_raises=True)
    try:
        yield channel
    finally:
        await channel.close()


@pytest_asyncio.fixture
async def declared_event_topology(
    rabbitmq_channel: aio_pika.abc.AbstractChannel,
) -> DeclaredEventTopology:
    topology = await EventTopologyBuilder().declare(
        rabbitmq_channel,
        retry_ttls_ms=INTEGRATION_RETRY_TTLS_MS,
    )
    for queue in (
        topology.event_queue,
        *topology.retry_queues,
        topology.dlq_queue,
    ):
        await queue.purge()
    return topology
