"""Unit tests for event routing key / message type parity."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from cps.contracts.messages.delivery import (
    HEADER_ATTEMPT,
    HEADER_CORRELATION_ID,
    HEADER_MAX_ATTEMPTS,
    HEADER_MESSAGE_ID,
    HEADER_ORIGINAL_ROUTING_KEY,
    HEADER_RETRY_REASON,
    HEADER_TRANSPORT_VERSION,
    SUPPORTED_TRANSPORT_VERSION,
    DeliveryMetadata,
    parse_delivery_metadata,
)
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import (
    OPERATION_COMPLETED,
    OPERATION_FAILED,
    OPERATION_PROGRESS,
)
from cps.infrastructure.messaging.inbox_consumer import DeliveryProcessingRecord, EventInboxConsumer
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher
from cps.infrastructure.messaging.retry import resolve_event_routing_key

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "src" / "cps" / "contracts" / "fixtures" / "events"
)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _headers(
    *,
    message_id: uuid.UUID,
    correlation_id: uuid.UUID,
    attempt: int = 1,
    original_routing_key: str | None = None,
) -> dict[str, Any]:
    payload = {
        HEADER_TRANSPORT_VERSION: SUPPORTED_TRANSPORT_VERSION,
        HEADER_MESSAGE_ID: str(message_id),
        HEADER_CORRELATION_ID: str(correlation_id),
        HEADER_ATTEMPT: attempt,
        HEADER_MAX_ATTEMPTS: 3,
    }
    if original_routing_key is not None:
        payload[HEADER_ORIGINAL_ROUTING_KEY] = original_routing_key
        payload[HEADER_RETRY_REASON] = "INBOX_HANDLER_ERROR"
    return payload


def _metadata(headers: dict[str, Any]) -> DeliveryMetadata:
    return parse_delivery_metadata(headers)


@pytest.mark.parametrize(
    ("fixture_name", "routing_key"),
    [
        ("operation_progress.json", OPERATION_PROGRESS),
        ("operation_completed.json", OPERATION_COMPLETED),
        ("operation_failed.json", OPERATION_FAILED),
    ],
)
def test_valid_routing_pairs_pass(fixture_name: str, routing_key: str) -> None:
    payload = _load_fixture(fixture_name)
    envelope = MessageEnvelope.model_validate(payload)
    metadata = _metadata(
        _headers(
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
        )
    )
    assert resolve_event_routing_key(envelope, metadata, routing_key) == envelope.message_type


def test_completed_envelope_on_progress_routing_key_rejects() -> None:
    payload = _load_fixture("operation_completed.json")
    envelope = MessageEnvelope.model_validate(payload)
    metadata = _metadata(
        _headers(message_id=envelope.message_id, correlation_id=envelope.correlation_id)
    )
    with pytest.raises(ValueError, match="routing key does not match message type"):
        resolve_event_routing_key(envelope, metadata, OPERATION_PROGRESS)


def test_failed_envelope_on_completed_routing_key_rejects() -> None:
    payload = _load_fixture("operation_failed.json")
    envelope = MessageEnvelope.model_validate(payload)
    metadata = _metadata(
        _headers(message_id=envelope.message_id, correlation_id=envelope.correlation_id)
    )
    with pytest.raises(ValueError, match="routing key does not match message type"):
        resolve_event_routing_key(envelope, metadata, OPERATION_COMPLETED)


def test_retry_original_routing_key_mismatch_rejects() -> None:
    payload = _load_fixture("operation_completed.json")
    envelope = MessageEnvelope.model_validate(payload)
    metadata = _metadata(
        _headers(
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            attempt=2,
            original_routing_key=OPERATION_PROGRESS,
        )
    )
    with pytest.raises(ValueError, match="original routing key does not match message type"):
        resolve_event_routing_key(envelope, metadata, "cloud.operation.retry")


class _FakeMessage:
    def __init__(self, *, body: bytes, headers: dict[str, Any], routing_key: str) -> None:
        self.body = body
        self.headers = headers
        self.routing_key = routing_key
        self.acked = False
        self.rejected = False
        self.reject_requeue = None

    async def ack(self, multiple: bool = False) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True
        self.reject_requeue = requeue


class _FakeExchange:
    async def publish(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_consumer_rejects_routing_mismatch_without_handler(monkeypatch) -> None:
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("handler must not run")

    payload = _load_fixture("operation_completed.json")
    body = json.dumps(payload).encode()
    envelope = MessageEnvelope.model_validate(payload)
    consumer = EventInboxConsumer(
        lifecycle=WorkerLifecycle(),
        publisher=ConfirmedPublisher(),
        retry_exchange=_FakeExchange(),
        session_factory=lambda: None,
    )
    monkeypatch.setattr(consumer, "_process_inbox", fail_if_called)
    message = _FakeMessage(
        body=body,
        headers=_headers(
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
        ),
        routing_key=OPERATION_PROGRESS,
    )
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(message, record)
    assert record.rejected is True
    assert record.handler_called is False
