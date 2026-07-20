"""Operation state machine constants."""

from __future__ import annotations

from collections.abc import Mapping

from cps.infrastructure.db.models.enums import OperationState

TERMINAL_STATES: frozenset[OperationState] = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.TIMED_OUT,
    }
)

ALLOWED_TRANSITIONS: Mapping[OperationState, frozenset[OperationState]] = {
    OperationState.ACCEPTED: frozenset({OperationState.QUEUED}),
    OperationState.QUEUED: frozenset(
        {
            OperationState.RUNNING,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    ),
    OperationState.RUNNING: frozenset(
        {
            OperationState.WAITING_PROVIDER,
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    ),
    OperationState.WAITING_PROVIDER: frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    ),
    OperationState.SUCCEEDED: frozenset(),
    OperationState.FAILED: frozenset(),
    OperationState.TIMED_OUT: frozenset(),
}
