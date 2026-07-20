"""CPS-104 Task 4: operation state machine unit tests."""

from __future__ import annotations

import pytest

from cps.domain.operations.errors import InvalidOperationTransitionError
from cps.domain.operations.states import ALLOWED_TRANSITIONS, TERMINAL_STATES
from cps.domain.operations.transitions import validate_transition
from cps.infrastructure.db.models.enums import OperationState


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (OperationState.ACCEPTED, OperationState.QUEUED),
        (OperationState.QUEUED, OperationState.RUNNING),
        (OperationState.QUEUED, OperationState.FAILED),
        (OperationState.QUEUED, OperationState.TIMED_OUT),
        (OperationState.RUNNING, OperationState.WAITING_PROVIDER),
        (OperationState.RUNNING, OperationState.SUCCEEDED),
        (OperationState.RUNNING, OperationState.FAILED),
        (OperationState.RUNNING, OperationState.TIMED_OUT),
        (OperationState.WAITING_PROVIDER, OperationState.SUCCEEDED),
        (OperationState.WAITING_PROVIDER, OperationState.FAILED),
        (OperationState.WAITING_PROVIDER, OperationState.TIMED_OUT),
    ],
)
def test_allowed_transitions(from_state: OperationState, to_state: OperationState) -> None:
    validate_transition(from_state, to_state)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (OperationState.ACCEPTED, OperationState.RUNNING),
        (OperationState.ACCEPTED, OperationState.SUCCEEDED),
        (OperationState.QUEUED, OperationState.SUCCEEDED),
        (OperationState.RUNNING, OperationState.QUEUED),
        (OperationState.WAITING_PROVIDER, OperationState.RUNNING),
        (OperationState.SUCCEEDED, OperationState.RUNNING),
        (OperationState.FAILED, OperationState.QUEUED),
        (OperationState.TIMED_OUT, OperationState.RUNNING),
        (OperationState.ACCEPTED, OperationState.ACCEPTED),
        (OperationState.RUNNING, OperationState.RUNNING),
        (OperationState.SUCCEEDED, OperationState.SUCCEEDED),
    ],
)
def test_forbidden_transitions(from_state: OperationState, to_state: OperationState) -> None:
    with pytest.raises(InvalidOperationTransitionError):
        validate_transition(from_state, to_state)


def test_terminal_states_are_frozen() -> None:
    assert TERMINAL_STATES == frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    )
    for terminal_state in TERMINAL_STATES:
        for target in OperationState:
            with pytest.raises(InvalidOperationTransitionError):
                validate_transition(terminal_state, target)


def test_allowed_transitions_matrix_matches_canonical_spec() -> None:
    assert ALLOWED_TRANSITIONS[OperationState.ACCEPTED] == frozenset({OperationState.QUEUED})
    assert ALLOWED_TRANSITIONS[OperationState.QUEUED] == frozenset(
        {
            OperationState.RUNNING,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    )
    assert ALLOWED_TRANSITIONS[OperationState.RUNNING] == frozenset(
        {
            OperationState.WAITING_PROVIDER,
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    )
    assert ALLOWED_TRANSITIONS[OperationState.WAITING_PROVIDER] == frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
        }
    )
    for terminal_state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[terminal_state] == frozenset()
