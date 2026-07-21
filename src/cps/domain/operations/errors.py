"""Operation domain errors."""

from __future__ import annotations


class InvalidOperationTransitionError(Exception):
    """Raised when an operation state transition is not allowed."""


class OperationNotFoundError(Exception):
    """Raised when the requested operation does not exist."""


class ConcurrentUpdateError(Exception):
    """Raised when an optimistic concurrency check fails."""


class InvalidProgressStateError(Exception):
    """Raised when progress cannot be recorded in the current state."""


class InvalidProgressValueError(Exception):
    """Raised when a progress percent value is invalid."""


class UnsafeEventDetailsError(Exception):
    """Raised when event details contain disallowed content."""


class OperationPersistenceError(Exception):
    """Raised when operation persistence fails for a non-concurrency reason."""


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request payload."""
