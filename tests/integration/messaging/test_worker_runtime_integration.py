"""Runtime integration: worker consumes a live event and updates PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import uuid

import aio_pika
import pytest

from cps.config import Settings
from cps.infrastructure.db.models.operations import Operation
from cps.messaging.runtime import run_worker
from tests.integration.db.seed_helpers import seed_operation_graph
from tests.integration.messaging.conftest import INTEGRATION_RETRY_TTLS_MS
from tests.integration.messaging.inbox_helpers import (
    advance_operation_to_running,
    bind_fixture_to_operation,
    delivery_headers,
    load_event_fixture,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_consumer_start_updates_database(
    db_tx,
    db_session_factory,
    rabbitmq_connection,
    declared_event_topology,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    from tests.integration.messaging.ack_policy_support import build_consumer, publish_event

    consumer_channel = await rabbitmq_connection.channel(publisher_confirms=True)
    consumer = build_consumer(
        db_session_factory=db_session_factory,
        topology=declared_event_topology,
        channel=consumer_channel,
    )
    await consumer.start(consumer_channel, declared_event_topology.event_queue)
    await publish_event(
        declared_event_topology,
        fixture=fixture,
        routing_key="cloud.operation.progress",
    )
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        async with db_session_factory() as session:
            operation = await session.get(Operation, operation_id)
            if operation is not None and operation.progress_percent == 25:
                break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("consumer.start did not update operation progress")
    await consumer.stop_session()


@pytest.mark.asyncio
async def test_runtime_consumes_live_event_and_updates_database(
    db_tx,
    db_session_factory,
    integration_database_url,
    disposable_vhost_manager,
    declared_event_topology,
    rabbitmq_connection,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )

    settings = Settings(
        environment="test",
        database_url=integration_database_url,
        rabbitmq_url=disposable_vhost_manager.integration_url,
        _env_file=None,
    )
    stop_event = asyncio.Event()

    async def fake_connect(url: str, **kwargs):
        return rabbitmq_connection

    worker_task = asyncio.create_task(
        run_worker(
            settings=settings,
            once=False,
            stop_event=stop_event,
            connect=fake_connect,
            retry_ttls_ms=INTEGRATION_RETRY_TTLS_MS,
            session_factory=db_session_factory,
        )
    )
    for _ in range(50):
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited before publish: {exc!r}")
        await asyncio.sleep(0.1)

    connection = await aio_pika.connect_robust(
        disposable_vhost_manager.integration_url,
        timeout=5,
        heartbeat=30,
    )
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        "cmp.cloud.event.v1", aio_pika.ExchangeType.TOPIC, passive=True
    )
    body = json.dumps(fixture).encode()
    headers = delivery_headers(
        message_id=uuid.UUID(fixture["message_id"]),
        correlation_id=uuid.UUID(fixture["correlation_id"]),
    )
    await exchange.publish(
        aio_pika.Message(
            body=body, headers=headers, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key="cloud.operation.progress",
    )

    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        async with db_session_factory() as session:
            operation = await session.get(Operation, operation_id)
            if operation is not None and operation.progress_percent == 25:
                break
        await asyncio.sleep(0.2)
    else:
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited before processing event: {exc!r}")
        pytest.fail("operation progress was not updated by runtime worker")

    stop_event.set()
    await asyncio.wait_for(worker_task, timeout=10)
    await connection.close()


@pytest.mark.asyncio
async def test_runtime_reconnects_after_forced_disconnect_and_consumes_again(
    db_tx,
    db_session_factory,
    integration_database_url,
    disposable_vhost_manager,
    declared_event_topology,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    fixture_a = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=uuid.uuid4(),
    )
    fixture_b = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=uuid.uuid4(),
    )
    fixture_b["payload"] = {"progress": 50, "message": "halfway complete"}

    settings = Settings(
        environment="test",
        database_url=integration_database_url,
        rabbitmq_url=disposable_vhost_manager.integration_url,
        _env_file=None,
    )
    stop_event = asyncio.Event()
    connect_calls = 0
    worker_connection = await aio_pika.connect_robust(
        disposable_vhost_manager.integration_url,
        timeout=5,
        heartbeat=30,
    )

    async def fake_connect(url: str, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return worker_connection
        return await aio_pika.connect_robust(url, **kwargs)

    worker_task = asyncio.create_task(
        run_worker(
            settings=settings,
            once=False,
            stop_event=stop_event,
            connect=fake_connect,
            retry_ttls_ms=INTEGRATION_RETRY_TTLS_MS,
            session_factory=db_session_factory,
        )
    )
    for _ in range(50):
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited before publish: {exc!r}")
        await asyncio.sleep(0.1)

    publisher_connection = await aio_pika.connect_robust(
        disposable_vhost_manager.integration_url,
        timeout=5,
        heartbeat=30,
    )
    channel = await publisher_connection.channel()
    exchange = await channel.declare_exchange(
        "cmp.cloud.event.v1", aio_pika.ExchangeType.TOPIC, passive=True
    )

    async def publish_fixture(fixture: dict) -> None:
        body = json.dumps(fixture).encode()
        headers = delivery_headers(
            message_id=uuid.UUID(fixture["message_id"]),
            correlation_id=uuid.UUID(fixture["correlation_id"]),
        )
        await exchange.publish(
            aio_pika.Message(
                body=body, headers=headers, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key="cloud.operation.progress",
        )

    await publish_fixture(fixture_a)
    deadline = asyncio.get_event_loop().time() + 15
    while asyncio.get_event_loop().time() < deadline:
        async with db_session_factory() as session:
            operation = await session.get(Operation, operation_id)
            if operation is not None and operation.progress_percent == 25:
                break
        await asyncio.sleep(0.2)
    else:
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited before processing first event: {exc!r}")
        pytest.fail("first event was not processed")

    await worker_connection.close()
    reconnect_deadline = asyncio.get_event_loop().time() + 15
    while asyncio.get_event_loop().time() < reconnect_deadline:
        if connect_calls >= 2 and not worker_task.done():
            break
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited during reconnect: {exc!r}")
        await asyncio.sleep(0.2)
    else:
        pytest.fail("worker did not reconnect after connection loss")

    await asyncio.sleep(1.0)
    await publish_fixture(fixture_b)
    second_deadline = asyncio.get_event_loop().time() + 15
    while asyncio.get_event_loop().time() < second_deadline:
        if worker_task.done():
            exc = worker_task.exception()
            pytest.fail(f"worker exited before processing second event: {exc!r}")
        async with db_session_factory() as session:
            operation = await session.get(Operation, operation_id)
            if operation is not None and operation.progress_percent == 50:
                break
        await asyncio.sleep(0.2)
    else:
        pytest.fail("second event was not processed after reconnect")

    stop_event.set()
    await asyncio.wait_for(worker_task, timeout=15)
    await publisher_connection.close()
