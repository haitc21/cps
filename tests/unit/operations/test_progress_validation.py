"""CPS-104: progress value validation unit tests."""

from __future__ import annotations

import pytest

from cps.domain.operations.errors import InvalidProgressValueError
from cps.domain.operations.progress import validate_progress_percent

_SECRET = "not-a-percent"  # pragma: allowlist secret


@pytest.mark.parametrize("value", [0, 100])
def test_validate_progress_percent_accepts_boundaries(value: int) -> None:
    validate_progress_percent(value)


@pytest.mark.parametrize("value", [-1, 101])
def test_validate_progress_percent_rejects_out_of_range(value: int) -> None:
    with pytest.raises(
        InvalidProgressValueError, match="progress value is not allowed"
    ) as exc_info:
        validate_progress_percent(value)
    assert _SECRET not in str(exc_info.value)


def test_validate_progress_percent_rejects_bool() -> None:
    with pytest.raises(InvalidProgressValueError):
        validate_progress_percent(True)  # type: ignore[arg-type]


def test_validate_progress_percent_rejects_string_and_float() -> None:
    with pytest.raises(InvalidProgressValueError):
        validate_progress_percent("50")  # type: ignore[arg-type]
    with pytest.raises(InvalidProgressValueError):
        validate_progress_percent(50.5)  # type: ignore[arg-type]
