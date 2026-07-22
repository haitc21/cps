"""Typed boundaries for CPS inbox deduplication."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class InboxValidationError(ValueError):
    """Raised for stable inbox input violations."""


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamp must be timezone-aware UTC"
        raise InboxValidationError(msg)
    if value.utcoffset() != UTC.utcoffset(value):
        msg = "timestamp must be UTC"
        raise InboxValidationError(msg)
    return value


@dataclass(frozen=True, slots=True)
class InboxReceiveDraft:
    """Unpersisted inbox row to insert inside the caller UoW."""

    consumer_name: str
    message_id: uuid.UUID
    message_type: str
    payload: dict[str, Any]
    received_at: datetime

    def __post_init__(self) -> None:
        if not self.consumer_name:
            raise InboxValidationError("consumer name is required")
        if not self.message_type:
            raise InboxValidationError("message type is required")
        _require_utc(self.received_at)
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))


class InboxInsertStatus(str, Enum):
    INSERTED = "inserted"
    ALREADY_PROCESSED = "already_processed"


@dataclass(frozen=True, slots=True)
class InboxInsertResult:
    status: InboxInsertStatus
    inbox_id: uuid.UUID | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.status is InboxInsertStatus.ALREADY_PROCESSED

    @property
    def requires_processing(self) -> bool:
        return self.status is InboxInsertStatus.INSERTED and self.inbox_id is not None


@dataclass(frozen=True, slots=True)
class InboxProcessOutcome:
    """Result of inbox insert + domain handler within one UoW transaction."""

    duplicate: bool
    committed: bool
