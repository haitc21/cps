"""Operation domain package."""

from __future__ import annotations

from cps.domain.operations.errors import (
    ConcurrentUpdateError,
    InvalidOperationTransitionError,
    InvalidProgressStateError,
    InvalidProgressValueError,
    OperationNotFoundError,
    OperationPersistenceError,
    UnsafeEventDetailsError,
)
from cps.domain.operations.states import ALLOWED_TRANSITIONS, TERMINAL_STATES
from cps.domain.operations.transitions import validate_transition

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ConcurrentUpdateError",
    "InvalidOperationTransitionError",
    "InvalidProgressStateError",
    "InvalidProgressValueError",
    "OperationNotFoundError",
    "OperationPersistenceError",
    "TERMINAL_STATES",
    "UnsafeEventDetailsError",
    "validate_transition",
]
