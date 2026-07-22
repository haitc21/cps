"""Retry republish helpers for CPS event deliveries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aio_pika.abc import AbstractExchange

from cps.contracts.messages.delivery import (
    DEFAULT_MAX_ATTEMPTS,
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
from cps.infrastructure.messaging.constants import (
    ROUTING_KEY_CLOUD_OPERATION_RETRY,
    ROUTING_KEY_CPS_EVENT_RETRY_1,
    ROUTING_KEY_CPS_EVENT_RETRY_2,
)
from cps.infrastructure.messaging.publisher import ConfirmedPublisher

EVENT_ROUTING_KEYS = frozenset(
    {
        "cloud.operation.progress",
        "cloud.operation.completed",
        "cloud.operation.failed",
    }
)


class RetryTierError(ValueError):
    """Raised when no AMQP retry tier exists for the current attempt."""


def normalize_delivery_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Apply fresh-message defaults for missing owned delivery headers."""
    normalized = dict(headers)
    normalized.setdefault(HEADER_TRANSPORT_VERSION, SUPPORTED_TRANSPORT_VERSION)
    normalized.setdefault(HEADER_ATTEMPT, 1)
    normalized.setdefault(HEADER_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS)
    return normalized


def merge_envelope_delivery_headers(
    headers: Mapping[str, Any] | None,
    envelope: MessageEnvelope,
) -> dict[str, Any]:
    """Fill fresh-message delivery IDs from the envelope when OPS omits AMQP headers."""
    merged = dict(headers or {})
    header_message_id = merged.get(HEADER_MESSAGE_ID)
    if header_message_id is not None and str(header_message_id) != str(envelope.message_id):
        msg = "delivery header message id does not match envelope"
        raise ValueError(msg)
    header_correlation_id = merged.get(HEADER_CORRELATION_ID)
    if header_correlation_id is not None and str(header_correlation_id) != str(
        envelope.correlation_id
    ):
        msg = "delivery header correlation id does not match envelope"
        raise ValueError(msg)
    merged.setdefault(HEADER_MESSAGE_ID, str(envelope.message_id))
    merged.setdefault(HEADER_CORRELATION_ID, str(envelope.correlation_id))
    return merged


def parse_event_delivery_metadata(headers: dict[str, Any]) -> DeliveryMetadata:
    """Parse owned delivery metadata from full AMQP headers."""
    metadata = parse_delivery_metadata(normalize_delivery_headers(headers))
    if metadata.max_attempts != DEFAULT_MAX_ATTEMPTS:
        msg = "unsupported runtime max attempts"
        raise ValueError(msg)
    return metadata


def select_retry_routing_key(current_attempt: int) -> str:
    if current_attempt == 1:
        return ROUTING_KEY_CPS_EVENT_RETRY_1
    if current_attempt == 2:
        return ROUTING_KEY_CPS_EVENT_RETRY_2
    msg = "no retry tier for current attempt"
    raise RetryTierError(msg)


def resolve_event_routing_key(
    envelope: MessageEnvelope,
    metadata: DeliveryMetadata,
    delivery_routing_key: str,
) -> str:
    """Resolve the canonical operation routing key and enforce message-type parity."""
    expected = envelope.message_type
    if metadata.attempt == 1:
        if metadata.original_routing_key is not None:
            msg = "invalid fresh event routing metadata"
            raise ValueError(msg)
        if delivery_routing_key != expected:
            msg = "routing key does not match message type"
            raise ValueError(msg)
        return expected
    if delivery_routing_key != ROUTING_KEY_CLOUD_OPERATION_RETRY:
        msg = "invalid retry event routing metadata"
        raise ValueError(msg)
    if metadata.original_routing_key != expected:
        msg = "original routing key does not match message type"
        raise ValueError(msg)
    return expected


def resolve_original_event_routing_key(
    metadata: DeliveryMetadata,
    delivery_routing_key: str,
) -> str:
    if metadata.attempt == 1:
        if (
            metadata.original_routing_key is not None
            or delivery_routing_key not in EVENT_ROUTING_KEYS
        ):
            msg = "invalid fresh event routing metadata"
            raise ValueError(msg)
        return delivery_routing_key
    if (
        delivery_routing_key != ROUTING_KEY_CLOUD_OPERATION_RETRY
        or metadata.original_routing_key not in EVENT_ROUTING_KEYS
    ):
        msg = "invalid retry event routing metadata"
        raise ValueError(msg)
    return metadata.original_routing_key


def build_retry_wire_headers(
    metadata: DeliveryMetadata,
    *,
    retry_reason: str,
    original_routing_key: str,
    next_attempt: int,
) -> dict[str, Any]:
    retry_model = DeliveryMetadata.model_validate(
        {
            HEADER_TRANSPORT_VERSION: SUPPORTED_TRANSPORT_VERSION,
            HEADER_MESSAGE_ID: str(metadata.message_id),
            HEADER_CORRELATION_ID: str(metadata.correlation_id),
            HEADER_ATTEMPT: next_attempt,
            HEADER_MAX_ATTEMPTS: metadata.max_attempts,
            HEADER_RETRY_REASON: retry_reason,
            HEADER_ORIGINAL_ROUTING_KEY: original_routing_key,
        }
    )
    return retry_model.model_dump(by_alias=True, mode="json")


async def publish_event_retry(
    publisher: ConfirmedPublisher,
    retry_exchange: AbstractExchange,
    *,
    body: bytes,
    metadata: DeliveryMetadata,
    retry_reason: str,
    original_routing_key: str,
) -> None:
    next_attempt = metadata.attempt + 1
    routing_key = select_retry_routing_key(metadata.attempt)
    headers = build_retry_wire_headers(
        metadata,
        retry_reason=retry_reason,
        original_routing_key=original_routing_key,
        next_attempt=next_attempt,
    )
    await publisher.publish(retry_exchange, routing_key, body, headers=headers)
