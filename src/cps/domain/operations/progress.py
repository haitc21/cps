"""Progress percent validation for operation updates."""

from __future__ import annotations

from cps.domain.operations.errors import InvalidProgressValueError


def validate_progress_percent(value: object) -> int:
    if type(value) is not int:
        msg = "progress value is not allowed"
        raise InvalidProgressValueError(msg)
    if value < 0 or value > 100:
        msg = "progress value is not allowed"
        raise InvalidProgressValueError(msg)
    return value
