"""Inbox handler failure and RabbitMQ integration tests."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aio_pika
import pytest
from sqlalchemy import func, select

from cps.domain.operations.errors import OperationNotFoundError
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.messaging.inbox_consumer import DeliveryProcessingRecord, EventInboxConsumer
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher
from cps.infrastructure.messaging.topology import EventTopologyBuilder
from tests.integration.db.seed_helpers import seed_operation_graph
from tests.integration.messaging.conftest import INTEGRATION_RETRY_TTLS_MS
from tests.integration.messaging.inbox_helpers import (
    advance_operation_to_running,
    bind_fixture_to_operation,
    delivery_headers,
    load_event_fixture,
    process_event_once,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_handler_failure_rolls_back_inbox_and_operation(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=new_uuid7(),
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )

    with pytest.raises(OperationNotFoundError):
        await process_event_once(db_session_factory, fixture)

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.message_id == message_id,
            )
        )
    assert inbox_count == 0


@pytest.mark.asyncio
async def test_progress_completed_and_failed_on_separate_operations(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    failed_graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    failed_operation_id = failed_graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    await advance_operation_to_running(failed_operation_id, db_session_factory)

    progress_fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    await process_event_once(db_session_factory, progress_fixture)

    completed_fixture = bind_fixture_to_operation(
        load_event_fixture("operation_completed.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=new_uuid7(),
    )
    await process_event_once(db_session_factory, completed_fixture)

    failed_fixture = bind_fixture_to_operation(
        load_event_fixture("operation_failed.json"),
        operation_id=failed_operation_id,
        provider_id=failed_graph["provider_id"],
        provider_connection_id=failed_graph["connection_id"],
        message_id=new_uuid7(),
    )
    await process_event_once(db_session_factory, failed_fixture)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        failed_operation = await session.get(Operation, failed_operation_id)
        progress_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == "PROGRESS",
            )
        )
    assert operation is not None
    assert failed_operation is not None
    assert operation.state is OperationState.SUCCEEDED
    assert operation.result_payload is not None
    assert operation.progress_percent == 25
    assert failed_operation.state is OperationState.FAILED
    assert failed_operation.error_payload is not None
    assert progress_count == 1


@pytest.mark.asyncio
async def test_unknown_operation_id_is_non_retryable(
    db_session_factory,
) -> None:
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=new_uuid7(),
        provider_id=new_uuid7(),
        provider_connection_id=new_uuid7(),
    )
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=_FakeExchange(),
        session_factory=db_session_factory,
    )
    body = json.dumps(fixture).encode()
    message = _FakeMessage(
        body=body,
        headers=delivery_headers(
            message_id=uuid.UUID(fixture["message_id"]),
            correlation_id=uuid.UUID(fixture["correlation_id"]),
        ),
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert record.retry_published is False


@pytest.mark.asyncio
async def test_topology_declaration_is_idempotent(
    rabbitmq_channel,
) -> None:
    builder = EventTopologyBuilder()
    first = await builder.declare(rabbitmq_channel, retry_ttls_ms=INTEGRATION_RETRY_TTLS_MS)
    second = await builder.declare(rabbitmq_channel, retry_ttls_ms=INTEGRATION_RETRY_TTLS_MS)
    assert first.event_queue.name == second.event_queue.name


@pytest.mark.asyncio
async def test_valid_event_publish_commit_ack(
    db_tx,
    db_session_factory,
    rabbitmq_channel,
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
    body = json.dumps(fixture).encode()
    headers = delivery_headers(
        message_id=uuid.UUID(fixture["message_id"]),
        correlation_id=uuid.UUID(fixture["correlation_id"]),
    )
    await declared_event_topology.event_exchange.publish(
        aio_pika.Message(
            body=body, headers=headers, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key="cloud.operation.progress",
    )

    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=declared_event_topology.retry_exchange,
        session_factory=db_session_factory,
    )
    queue = declared_event_topology.event_queue
    incoming = await queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(
        _IncomingAdapter(incoming),
        record,
    )
    assert completed is True
    assert record.acked is True
    assert record.committed is True

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
    assert operation is not None
    assert operation.progress_percent == 25


class _FakeExchange:
    async def publish(self, *args, **kwargs):
        return None


class _FakeMessage:
    def __init__(self, *, body: bytes, headers: dict[str, Any]) -> None:
        self.body = body
        self.headers = headers
        self.routing_key = "cloud.operation.progress"
        self.acked = False
        self.rejected = False
        self.reject_requeue = None

    async def ack(self, multiple: bool = False) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True
        self.reject_requeue = requeue


class _IncomingAdapter:
    def __init__(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        self._message = message
        self.body = message.body
        self.headers = message.headers
        self.routing_key = message.routing_key

    async def ack(self, multiple: bool = False) -> None:
        await self._message.ack(multiple=multiple)

    async def reject(self, requeue: bool = False) -> None:
        await self._message.reject(requeue=requeue)
