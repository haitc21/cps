"""Safe validation boundary for operation event details."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cps.domain.operations.errors import UnsafeEventDetailsError

_MAX_NESTING_DEPTH = 32
_UNSAFE_MESSAGE = "event details are not allowed"
_VALIDATED = object()

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")
_SEPARATOR_NORMALIZER = re.compile(r"[\s\-]+")

_FORBIDDEN_EXACT_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "authorization_header",
        "user_data",
        "dsn",
        "database_url",
        "raw_response",
        "response_body",
        "private_key",
        "api_key",
        "secret_key",
        "access_token",
        "refresh_token",
        "auth_token",
        "client_secret",
        "api_secret",
    }
)

_SAFE_METADATA_SUFFIXES = frozenset(
    {
        "count",
        "policy",
        "status",
        "rotation",
        "name",
        "type",
        "id",
        "enabled",
        "expires",
    }
)

_FORBIDDEN_TERMINAL_TOKENS = frozenset({"password", "token", "secret"})
_FORBIDDEN_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "x_api_key",
        "x_auth_token",
    }
)


def _raise_unsafe() -> None:
    raise UnsafeEventDetailsError(_UNSAFE_MESSAGE)


def _tokenize_key(key: str) -> tuple[str, ...]:
    step = key.strip()
    step = _CAMEL_ACRONYM.sub(r"\1_\2", step)
    step = _CAMEL_BOUNDARY.sub(r"\1_\2", step)
    step = _SEPARATOR_NORMALIZER.sub("_", step)
    return tuple(token for token in step.casefold().split("_") if token)


def _normalized_key(key: str) -> str:
    return "_".join(_tokenize_key(key))


def _is_safe_metadata_key(tokens: tuple[str, ...]) -> bool:
    return len(tokens) >= 2 and tokens[-1] in _SAFE_METADATA_SUFFIXES


def _is_forbidden_key(key: str) -> bool:
    tokens = _tokenize_key(key)
    if not tokens:
        return False
    normalized = "_".join(tokens)
    if normalized in _FORBIDDEN_EXACT_KEYS:
        return True
    if _is_safe_metadata_key(tokens):
        return False
    if "cookie" in tokens:
        return True
    if tokens[-1] in _FORBIDDEN_TERMINAL_TOKENS:
        return True
    if tokens[-1] == "key" and "private" in tokens:
        return True
    if tokens[-2:] == ("api", "key"):
        return True
    if "authorization" in tokens:
        return True
    return normalized.endswith("_token") or normalized.endswith("_secret")


def _is_forbidden_header_name(header_name: str) -> bool:
    normalized = _normalized_key(header_name)
    if normalized in _FORBIDDEN_HEADER_NAMES:
        return True
    tokens = _tokenize_key(header_name)
    if not tokens:
        return False
    if "cookie" in tokens:
        return True
    if tokens[-2:] == ("api", "key"):
        return True
    if tokens[-2:] == ("auth", "token"):
        return True
    return "authorization" in tokens


def _validate_headers_mapping(headers: Mapping[str, Any]) -> None:
    for header_name in headers:
        if isinstance(header_name, str) and _is_forbidden_header_name(header_name):
            _raise_unsafe()


def _validate_node(
    value: Any,
    *,
    depth: int = 0,
    active_ids: frozenset[int] = frozenset(),
) -> Any:
    if depth > _MAX_NESTING_DEPTH:
        _raise_unsafe()
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _raise_unsafe()
        return value
    if isinstance(value, bytes):
        _raise_unsafe()
    if isinstance(value, list):
        obj_id = id(value)
        if obj_id in active_ids:
            _raise_unsafe()
        next_active = active_ids | {obj_id}
        return [_validate_node(item, depth=depth + 1, active_ids=next_active) for item in value]
    if isinstance(value, tuple):
        _raise_unsafe()
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in active_ids:
            _raise_unsafe()
        next_active = active_ids | {obj_id}
        validated: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _raise_unsafe()
            if _is_forbidden_key(key):
                _raise_unsafe()
            if _normalized_key(key) == "headers" and isinstance(item, dict):
                _validate_headers_mapping(item)
            validated[key] = _validate_node(item, depth=depth + 1, active_ids=next_active)
        return validated
    _raise_unsafe()


@dataclass(frozen=True, slots=True)
class SafeEventDetails:
    """Immutable validated event details ready for persistence."""

    _payload: dict[str, Any]
    _validation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._validation_token is not _VALIDATED:
            _raise_unsafe()
        _validate_node(copy.deepcopy(self._payload))

    def __repr__(self) -> str:
        return "SafeEventDetails(redacted)"

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._payload)


def validate_event_details(raw: Mapping[str, Any] | None) -> SafeEventDetails:
    if raw is None:
        payload: dict[str, Any] = {}
    elif isinstance(raw, dict):
        payload = _validate_node(raw)
    else:
        _raise_unsafe()
    return SafeEventDetails(
        _payload=copy.deepcopy(payload),
        _validation_token=_VALIDATED,
    )


def materialize_event_details(details: SafeEventDetails) -> dict[str, Any]:
    """Re-validate details before persistence."""
    return validate_event_details(details.to_dict()).to_dict()
