"""PostgreSQL enum types for CPS persistence."""

from __future__ import annotations

import enum


class ProviderStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ConnectionStatus(str, enum.Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    VALID = "VALID"
    INVALID = "INVALID"
    DISABLED = "DISABLED"


class OperationState(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_PROVIDER = "WAITING_PROVIDER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class OutboxPublishState(str, enum.Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class InboxProcessState(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
