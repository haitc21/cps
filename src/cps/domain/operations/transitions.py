"""Operation transition validation."""

from __future__ import annotations

from cps.domain.operations.errors import InvalidOperationTransitionError
from cps.domain.operations.states import ALLOWED_TRANSITIONS, TERMINAL_STATES
from cps.infrastructure.db.models.enums import OperationState


def validate_transition(from_state: OperationState, to_state: OperationState) -> None:
    if from_state in TERMINAL_STATES:
        msg = "operation is in a terminal state"
        raise InvalidOperationTransitionError(msg)
    allowed_targets = ALLOWED_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed_targets:
        msg = "operation transition is not allowed"
        raise InvalidOperationTransitionError(msg)
