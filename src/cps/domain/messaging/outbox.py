"""Typed, immutable boundaries for CPS transactional outbox work."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cps.contracts.messages.delivery import (
    ALLOWED_ORIGINAL_ROUTING_KEYS,
    DEFAULT_MAX_ATTEMPTS,
    SUPPORTED_TRANSPORT_VERSION,
    DeliveryMetadata,
)
from cps.contracts.messages.envelope import MessageEnvelope

COMMAND_ROUTING_KEYS = frozenset(
    key for key in ALLOWED_ORIGINAL_ROUTING_KEYS if key.startswith("openstack.")
)
MAX_OUTBOX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS


class OutboxValidationError(ValueError):
    """Raised for stable, caller-correctable outbox input violations."""


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware UTC"
        raise OutboxValidationError(msg)
    if value.utcoffset() != UTC.utcoffset(value):
        msg = f"{field_name} must be UTC"
        raise OutboxValidationError(msg)
    return value


@dataclass(frozen=True, slots=True)
class OutboxDraft:
    """An unclaimed message to be persisted in the caller's UoW."""

    aggregate_type: str
    aggregate_id: uuid.UUID
    message_id: uuid.UUID
    message_type: str
    routing_key: str
    payload: dict[str, Any]
    correlation_id: uuid.UUID
    occurred_at: datetime
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        if not self.aggregate_type:
            raise OutboxValidationError("aggregate type is required")
        if self.routing_key not in COMMAND_ROUTING_KEYS:
            raise OutboxValidationError("routing key must be an allowed command routing key")
        if self.max_attempts != DEFAULT_MAX_ATTEMPTS:
            raise OutboxValidationError("max attempts must use canonical default")
        _require_utc(self.occurred_at, field_name="occurred at")
        try:
            envelope = MessageEnvelope.model_validate(copy.deepcopy(self.payload))
        except ValueError:
            raise OutboxValidationError("payload must be a valid message envelope") from None
        if envelope.message_id != self.message_id:
            raise OutboxValidationError("payload message id must match outbox message id")
        if envelope.correlation_id != self.correlation_id:
            raise OutboxValidationError("payload correlation id must match outbox correlation id")
        if envelope.message_type != self.message_type:
            raise OutboxValidationError("payload message type must match outbox message type")
        if self.aggregate_type == "operation" and envelope.operation_id != self.aggregate_id:
            raise OutboxValidationError("operation aggregate id must match envelope operation id")
        object.__setattr__(self, "payload", envelope.model_dump(mode="json"))

    @property
    def delivery_metadata(self) -> DeliveryMetadata:
        return DeliveryMetadata.model_validate(
            {
                "x-transport-version": SUPPORTED_TRANSPORT_VERSION,
                "x-message-id": self.message_id,
                "x-correlation-id": self.correlation_id,
                "x-attempt": 1,
                "x-max-attempts": self.max_attempts,
            }
        )


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    """Lease identity used for guarded finalization."""

    row_id: uuid.UUID
    claimed_by: str
    claim_token: uuid.UUID


@dataclass(frozen=True, slots=True)
class ClaimedOutboxMessage:
    """Detached message safe to publish after its claim transaction commits."""

    claim: OutboxClaim
    message_id: uuid.UUID
    message_type: str
    routing_key: str
    payload: dict[str, Any]
    correlation_id: uuid.UUID
    attempt_count: int
    max_attempts: int
    claim_expires_at: datetime
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.attempt_count < 1:
            raise OutboxValidationError("claimed attempt count must be positive")
        if self.attempt_count > self.max_attempts:
            raise OutboxValidationError("claimed attempt count exceeds maximum")
        _require_utc(self.claim_expires_at, field_name="claim expiry")
        _require_utc(self.occurred_at, field_name="occurred at")
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))

    @property
    def delivery_metadata(self) -> DeliveryMetadata:
        values: dict[str, Any] = {
            "x-transport-version": SUPPORTED_TRANSPORT_VERSION,
            "x-message-id": self.message_id,
            "x-correlation-id": self.correlation_id,
            "x-attempt": self.attempt_count,
            "x-max-attempts": self.max_attempts,
        }
        if self.attempt_count > 1:
            values["x-retry-reason"] = "OUTBOX_RETRY"
            values["x-original-routing-key"] = self.routing_key
        return DeliveryMetadata.model_validate(values)


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Outcome of a guarded finalize attempt."""

    finalized: bool
    stale: bool = False
