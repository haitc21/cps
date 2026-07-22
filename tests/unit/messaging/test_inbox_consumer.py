"""Unit tests for inbox consumer validation and ACK policy."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from pamqp.commands import Basic

from cps.contracts.messages.delivery import (
    HEADER_ATTEMPT,
    HEADER_CORRELATION_ID,
    HEADER_MAX_ATTEMPTS,
    HEADER_MESSAGE_ID,
    HEADER_ORIGINAL_ROUTING_KEY,
    HEADER_RETRY_REASON,
    HEADER_TRANSPORT_VERSION,
    SUPPORTED_TRANSPORT_VERSION,
)
from cps.domain.messaging.inbox import InboxProcessOutcome
from cps.domain.operations.errors import OperationNotFoundError, OperationPersistenceError
from cps.identifiers import new_uuid7
from cps.infrastructure.messaging.inbox_consumer import (
    DeliveryProcessingRecord,
    EventInboxConsumer,
)
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher

pytestmark = pytest.mark.asyncio

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "src" / "cps" / "contracts" / "fixtures" / "events"
)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class FakeMessage:
    def __init__(
        self,
        *,
        body: bytes,
        headers: dict[str, Any] | None = None,
        routing_key: str = "cloud.operation.progress",
        ack_raises: bool = False,
    ) -> None:
        self.body = body
        self.headers = headers
        self.routing_key = routing_key
        self.acked = False
        self.rejected = False
        self.reject_requeue: bool | None = None
        self.ack_raises = ack_raises
        self.ack_calls = 0

    async def ack(self, multiple: bool = False) -> None:
        self.ack_calls += 1
        if self.ack_raises:
            raise RuntimeError("ack failed")
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True
        self.reject_requeue = requeue


class FakeExchange:
    def __init__(self, *, confirmation: object | None = Basic.Ack()) -> None:
        self.confirmation = confirmation
        self.publishes: list[dict[str, Any]] = []

    async def publish(self, message, routing_key: str, **kwargs):
        self.publishes.append({"routing_key": routing_key, "headers": dict(message.headers or {})})
        return self.confirmation


class FakeSessionFactory:
    def __call__(self):
        raise OperationPersistenceError("session unavailable in unit test")


def _fresh_headers(message_id: uuid.UUID, correlation_id: uuid.UUID) -> dict[str, Any]:
    return {
        HEADER_TRANSPORT_VERSION: SUPPORTED_TRANSPORT_VERSION,
        HEADER_MESSAGE_ID: str(message_id),
        HEADER_CORRELATION_ID: str(correlation_id),
        HEADER_ATTEMPT: 1,
        HEADER_MAX_ATTEMPTS: 3,
    }


def _consumer(
    *,
    session_factory=None,
    retry_exchange: FakeExchange | None = None,
) -> EventInboxConsumer:
    return EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=retry_exchange or FakeExchange(),
        session_factory=session_factory or FakeSessionFactory(),
    )


async def test_malformed_json_rejects_once() -> None:
    consumer = _consumer()
    message = FakeMessage(body=b"not-json", headers=_fresh_headers(new_uuid7(), new_uuid7()))
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is False
    assert record.rejected is True
    assert record.reject_requeue is False
    assert record.terminal_action_count == 1
    assert record.acked is False


async def test_unknown_event_type_rejects_once() -> None:
    payload = _load_fixture("operation_progress.json")
    payload["message_type"] = "cloud.operation.unknown"
    body = json.dumps(payload).encode()
    consumer = _consumer()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert record.retry_published is False


async def test_ops_style_event_without_amqp_headers_is_accepted(monkeypatch) -> None:
    async def duplicate_process(*args, **kwargs):
        return InboxProcessOutcome(duplicate=True, committed=False)

    consumer = _consumer()
    monkeypatch.setattr(consumer, "_process_inbox", duplicate_process)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(body=body, headers=None)
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is True
    assert record.rejected is False
    assert record.acked is True


async def test_duplicate_skips_handler_and_acks(monkeypatch) -> None:
    async def duplicate_process(*args, **kwargs):
        return InboxProcessOutcome(duplicate=True, committed=False)

    consumer = _consumer()
    monkeypatch.setattr(consumer, "_process_inbox", duplicate_process)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is True
    assert record.acked is True
    assert record.handler_called is False


async def test_unknown_operation_rejects_without_retry(monkeypatch) -> None:
    async def raise_not_found(*args, **kwargs):
        raise OperationNotFoundError("operation not found")

    consumer = _consumer()
    monkeypatch.setattr(consumer, "_process_inbox", raise_not_found)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert record.retry_published is False


async def test_retry_confirm_before_ack(monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    retry_exchange = FakeExchange()
    consumer = _consumer(retry_exchange=retry_exchange)
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is True
    assert record.retry_published is True
    assert record.acked is True
    assert record.rejected is False
    assert retry_exchange.publishes[0]["routing_key"] == "cps.cloud.event.retry.1"


async def test_retry_confirm_failure_leaves_unacked(monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    class FailingChannel:
        is_closed = False
        closed = False

        async def close(self) -> None:
            self.closed = True
            self.is_closed = True

    retry_exchange = FakeExchange(confirmation=None)
    consumer = _consumer(retry_exchange=retry_exchange)
    consumer.channel = FailingChannel()
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is False
    assert record.acked is False
    assert record.rejected is False
    assert record.channel_closed is True


async def test_exhausted_attempt_rejects_once(monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    consumer = _consumer()
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    headers = _fresh_headers(uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"]))
    headers[HEADER_ATTEMPT] = 3
    message = FakeMessage(body=body, headers=headers)
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert record.retry_published is False


@pytest.mark.parametrize(
    ("attempt", "expected_routing_key"),
    [
        (1, "cps.cloud.event.retry.1"),
        (2, "cps.cloud.event.retry.2"),
    ],
)
async def test_retry_tier_matrix(attempt: int, expected_routing_key: str, monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    retry_exchange = FakeExchange()
    consumer = _consumer(retry_exchange=retry_exchange)
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    headers = _fresh_headers(uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"]))
    headers[HEADER_ATTEMPT] = attempt
    routing_key = "cloud.operation.progress"
    if attempt > 1:
        headers[HEADER_RETRY_REASON] = "INBOX_HANDLER_ERROR"
        headers[HEADER_ORIGINAL_ROUTING_KEY] = "cloud.operation.progress"
        routing_key = "cloud.operation.retry"
    message = FakeMessage(body=body, headers=headers, routing_key=routing_key)
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert retry_exchange.publishes[0]["routing_key"] == expected_routing_key
    assert retry_exchange.publishes[0]["headers"][HEADER_ATTEMPT] == attempt + 1


async def test_db_commit_success_ack_failure_closes_channel_without_retry(monkeypatch) -> None:
    class FailingChannel:
        is_closed = False

        async def close(self) -> None:
            self.is_closed = True

    async def committed_process(*args, **kwargs):
        return InboxProcessOutcome(duplicate=False, committed=True)

    consumer = _consumer()
    consumer.channel = FailingChannel()
    monkeypatch.setattr(consumer, "_process_inbox", committed_process)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
        ack_raises=True,
    )
    record = DeliveryProcessingRecord()
    _, completed = await consumer.process_delivery(message, record)
    assert completed is False
    assert record.committed is True
    assert record.retry_published is False
    assert record.rejected is False
    assert record.channel_closed is True
    assert message.ack_calls == 1


async def test_duplicate_ack_failure_does_not_retry(monkeypatch) -> None:
    class FailingChannel:
        is_closed = False

        async def close(self) -> None:
            self.is_closed = True

    async def duplicate_process(*args, **kwargs):
        return InboxProcessOutcome(duplicate=True, committed=False)

    consumer = _consumer()
    consumer.channel = FailingChannel()
    monkeypatch.setattr(consumer, "_process_inbox", duplicate_process)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
        ack_raises=True,
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.handler_called is False
    assert record.retry_published is False
    assert record.channel_closed is True


async def test_handler_failure_before_commit_retries_once(monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    retry_exchange = FakeExchange()
    consumer = _consumer(retry_exchange=retry_exchange)
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.committed is False
    assert len(retry_exchange.publishes) == 1
    assert record.retry_published is True
    assert record.acked is True


async def test_retry_confirm_success_ack_failure_does_not_publish_twice(monkeypatch) -> None:
    async def raise_persistence(*args, **kwargs):
        raise OperationPersistenceError("db failed")

    class FailingChannel:
        is_closed = False

        async def close(self) -> None:
            self.is_closed = True

    retry_exchange = FakeExchange()
    consumer = _consumer(retry_exchange=retry_exchange)
    consumer.channel = FailingChannel()
    monkeypatch.setattr(consumer, "_process_inbox", raise_persistence)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
        ack_raises=True,
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert len(retry_exchange.publishes) == 1
    assert record.retry_published is True
    assert record.rejected is False
    assert record.channel_closed is True


async def test_ack_success_has_exact_one_terminal_action(monkeypatch) -> None:
    async def committed_process(*args, **kwargs):
        return InboxProcessOutcome(duplicate=False, committed=True)

    consumer = _consumer()
    monkeypatch.setattr(consumer, "_process_inbox", committed_process)
    payload = _load_fixture("operation_progress.json")
    body = json.dumps(payload).encode()
    message = FakeMessage(
        body=body,
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.terminal_action_count == 1
    assert record.acked is True


async def test_in_flight_commit_during_shutdown_grace_is_acked(monkeypatch) -> None:
    lifecycle = WorkerLifecycle()

    async def committed_during_shutdown(*args, **kwargs):
        lifecycle.begin_shutdown()
        return InboxProcessOutcome(duplicate=False, committed=True)

    consumer = _consumer()
    consumer.lifecycle = lifecycle
    monkeypatch.setattr(consumer, "_process_inbox", committed_during_shutdown)
    payload = _load_fixture("operation_progress.json")
    message = FakeMessage(
        body=json.dumps(payload).encode(),
        headers=_fresh_headers(
            uuid.UUID(payload["message_id"]), uuid.UUID(payload["correlation_id"])
        ),
    )
    record = DeliveryProcessingRecord()

    await consumer.process_delivery(message, record)

    assert record.committed is True
    assert record.acked is True
    assert record.terminal_action_count == 1
    assert message.ack_calls == 1


async def test_shutdown_leaves_prefetched_delivery_unacked() -> None:
    lifecycle = WorkerLifecycle()
    lifecycle.begin_shutdown()
    consumer = _consumer()
    consumer.lifecycle = lifecycle
    message = FakeMessage(body=b"{}", headers=None)
    await consumer._on_message(message)
    assert message.acked is False
    assert message.rejected is False
    assert message.ack_calls == 0


async def test_stop_session_preserves_accepting_work() -> None:
    class FakeQueue:
        async def cancel(self, tag: str) -> None:
            return None

    class FakeChannel:
        is_closed = False

        async def close(self) -> None:
            self.is_closed = True

    lifecycle = WorkerLifecycle()
    consumer = EventInboxConsumer(
        lifecycle=lifecycle,
        publisher=ConfirmedPublisher(),
        retry_exchange=FakeExchange(),
        session_factory=FakeSessionFactory(),
    )
    consumer._consumer_tag = "tag-1"
    consumer._queue = FakeQueue()
    consumer.channel = FakeChannel()

    await consumer.stop_session()

    assert lifecycle.accepting_work is True


async def test_stop_begin_shutdown_and_closes_channel() -> None:
    class FakeQueue:
        def __init__(self) -> None:
            self.cancelled = False

        async def cancel(self, tag: str) -> None:
            self.cancelled = True

    class FakeChannel:
        is_closed = False

        async def close(self) -> None:
            self.is_closed = True

    lifecycle = WorkerLifecycle()
    consumer = _consumer()
    consumer.lifecycle = lifecycle
    consumer._consumer_tag = "tag-1"
    consumer._queue = FakeQueue()
    channel = FakeChannel()
    consumer.channel = channel

    await consumer.stop()

    assert lifecycle.accepting_work is False
    assert consumer._queue.cancelled is True
    assert channel.is_closed is True
    assert consumer.channel is None


async def test_validation_error_does_not_leak_body() -> None:
    consumer = _consumer()
    secret = "super-secret-token-value"  # pragma: allowlist secret
    message = FakeMessage(body=secret.encode(), headers=_fresh_headers(new_uuid7(), new_uuid7()))
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert secret not in str(record.__dict__)
