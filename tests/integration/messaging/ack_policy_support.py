"""Shared helpers for live RabbitMQ ack-policy integration tests."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue

from cps.infrastructure.messaging.constants import ROUTING_KEY_CLOUD_OPERATION_RETRY
from cps.infrastructure.messaging.inbox_consumer import (
    DeliveryProcessingRecord,
    EventInboxConsumer,
)
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher
from cps.infrastructure.messaging.topology import DeclaredEventTopology
from tests.integration.messaging.inbox_helpers import delivery_headers


class IncomingAdapter:
    def __init__(self, message: AbstractIncomingMessage) -> None:
        self._message = message
        self.body = message.body
        self.headers = message.headers
        self.routing_key = message.routing_key

    async def ack(self, multiple: bool = False) -> None:
        await self._message.ack(multiple=multiple)

    async def reject(self, requeue: bool = False) -> None:
        await self._message.reject(requeue=requeue)


@dataclass
class DeliveryOutcome:
    record: DeliveryProcessingRecord
    completed: bool


def build_consumer(
    *,
    db_session_factory,
    topology: DeclaredEventTopology,
    lifecycle: WorkerLifecycle | None = None,
    channel=None,
) -> EventInboxConsumer:
    return EventInboxConsumer(
        lifecycle=lifecycle or WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=topology.retry_exchange,
        session_factory=db_session_factory,
        channel=channel,
    )


async def publish_event(
    topology: DeclaredEventTopology,
    *,
    fixture: dict[str, Any],
    routing_key: str,
    attempt: int = 1,
    extra_headers: dict[str, Any] | None = None,
) -> None:
    body = json.dumps(fixture).encode()
    headers = delivery_headers(
        message_id=uuid.UUID(fixture["message_id"]),
        correlation_id=uuid.UUID(fixture["correlation_id"]),
        attempt=attempt,
    )
    if attempt > 1:
        headers["x-original-routing-key"] = routing_key
        headers["x-retry-reason"] = "INBOX_HANDLER_ERROR"
        routing_key = ROUTING_KEY_CLOUD_OPERATION_RETRY
    if extra_headers:
        headers.update(extra_headers)
    await topology.event_exchange.publish(
        aio_pika.Message(
            body=body, headers=headers, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key=routing_key,
    )


async def process_queue_message(
    consumer: EventInboxConsumer,
    queue: AbstractQueue,
    *,
    wait_seconds: float = 5,
) -> DeliveryOutcome:
    incoming = await queue.get(timeout=wait_seconds, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(IncomingAdapter(incoming), record)
    return DeliveryOutcome(record=record, completed=completed)


async def queue_depth(queue: AbstractQueue) -> int:
    result = await queue.channel.declare_queue(queue.name, passive=True)
    declaration = result.declaration_result
    if declaration is None:
        return 0
    return declaration.message_count


async def wait_for_queue_depth(
    queue: AbstractQueue,
    expected: int,
    *,
    wait_seconds: float = 2.0,
) -> int:
    deadline = asyncio.get_event_loop().time() + wait_seconds
    while asyncio.get_event_loop().time() < deadline:
        depth = await queue_depth(queue)
        if depth == expected:
            return depth
        await asyncio.sleep(0.05)
    return await queue_depth(queue)


async def take_dlq_message(
    queue: AbstractQueue, *, wait_seconds: float = 10.0
) -> AbstractIncomingMessage:
    """Poll DLQ until a message arrives or timeout (DLX routing can lag passive depth)."""
    await asyncio.sleep(0.1)
    deadline = asyncio.get_event_loop().time() + wait_seconds
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        message = await queue.get(timeout=max(0.05, min(remaining, 0.25)), fail=False)
        if message is not None:
            return message
    msg = "DLQ message not received"
    raise AssertionError(msg)


async def assert_exactly_one_terminal_action(record: DeliveryProcessingRecord) -> None:
    assert record.terminal_action_count == 1
