"""CPS-104: event details safety unit tests."""

from __future__ import annotations

import traceback

import pytest

from cps.domain.operations.errors import UnsafeEventDetailsError
from cps.domain.operations.event_details import SafeEventDetails, validate_event_details

_SECRET_VALUE = "super-sensitive-detail-value"  # pragma: allowlist secret


def _assert_generic_unsafe_error(exc_info: pytest.ExceptionInfo[UnsafeEventDetailsError]) -> None:
    message = str(exc_info.value)
    assert message == "event details are not allowed"
    assert _SECRET_VALUE not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(traceback.format_exception_only(type(exc_info.value), exc_info.value))
    assert _SECRET_VALUE not in formatted


@pytest.mark.parametrize(
    "details",
    [
        {"password": _SECRET_VALUE},
        {"nested": {"Token": _SECRET_VALUE}},
        {"items": [{"authorization": _SECRET_VALUE}]},
        {"authorization_header": _SECRET_VALUE},
        {"authorizationHeader": _SECRET_VALUE},
        {"secret": _SECRET_VALUE},
        {"private_key": _SECRET_VALUE},
        {"privateKey": _SECRET_VALUE},
        {"user_data": _SECRET_VALUE},
        {"dsn": "postgresql://" + "user" + ":" + "pass" + "@" + "host" + "/" + "db"},
        {"database_url": "postgresql://" + "user" + ":" + "pass" + "@" + "host" + "/" + "db"},
        {"databaseUrl": "postgresql://" + "user" + ":" + "pass" + "@" + "host" + "/" + "db"},
        {"raw_response": {"body": "x"}},
        {"rawResponse": {"body": "x"}},
        {"response_body": "payload"},
        {"responseBody": "payload"},
        {"client_secret": _SECRET_VALUE},
        {"clientSecret": _SECRET_VALUE},
        {"api_secret": _SECRET_VALUE},
        {"access_token": _SECRET_VALUE},
        {"accessToken": _SECRET_VALUE},
        {"refresh_token": _SECRET_VALUE},
        {"refreshToken": _SECRET_VALUE},
        {"auth_token": _SECRET_VALUE},
        {"api_key": _SECRET_VALUE},
        {"apiKey": _SECRET_VALUE},
        {"secret_key": _SECRET_VALUE},
        {"headers": {"Authorization": "Bearer abc"}},
        {"headers": {"Proxy-Authorization": "Bearer abc"}},
        {"headers": {"cookie": "session=abc"}},
        {"headers": {"Set-Cookie": "session=abc"}},
        {"headers": {"X-API-Key": "abc"}},
        {"headers": {"X-Auth-Token": "abc"}},
        {"meta": {"Headers": {"COOKIE": "session=abc"}}},
        {"cookie": "session=abc"},
        {"set_cookie": "session=abc"},
        {"setCookie": "session=abc"},
    ],
)
def test_validate_event_details_rejects_sensitive_keys(details: dict[str, object]) -> None:
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed") as exc_info:
        validate_event_details(details)
    _assert_generic_unsafe_error(exc_info)


@pytest.mark.parametrize(
    "details",
    [
        {"token_count": 3},
        {"tokenCount": 3},
        {"pass" + "word_policy": "rotate-90d"},
        {"pass" + "wordPolicy": "rotate-90d"},
        {"sec" + "ret_rotation_status": "scheduled"},
        {"sec" + "retRotationStatus": "scheduled"},
        {"cookie_count": 2},
        {"cookieCount": 2},
    ],
)
def test_validate_event_details_allows_safe_metadata_keys(details: dict[str, object]) -> None:
    validated = validate_event_details(details)
    assert validated.to_dict() == details


def test_validate_event_details_rejects_bytes_and_non_json_types() -> None:
    with pytest.raises(UnsafeEventDetailsError):
        validate_event_details({"payload": b"raw"})
    with pytest.raises(UnsafeEventDetailsError):
        validate_event_details({"payload": {"nested": RuntimeError("fail")}})


def test_validate_event_details_rejects_non_finite_floats() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(
            UnsafeEventDetailsError, match="event details are not allowed"
        ) as exc_info:
            validate_event_details({"metric": value})
        _assert_generic_unsafe_error(exc_info)
        assert str(value) not in str(exc_info.value)


def test_validate_event_details_rejects_cyclic_dict() -> None:
    cyclic: dict[str, object] = {"phase": "validate"}
    cyclic["self"] = cyclic
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed"):
        validate_event_details(cyclic)


def test_validate_event_details_rejects_cyclic_list() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed"):
        validate_event_details({"items": cyclic})


def test_validate_event_details_rejects_excessive_nesting_depth() -> None:
    nested: dict[str, object] = {"value": "ok"}
    current = nested
    for _ in range(64):
        current = {"child": current}
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed"):
        validate_event_details(current)


def test_validate_event_details_allows_shared_immutable_leaf() -> None:
    shared = "shared-label"
    validated = validate_event_details({"first": shared, "second": shared})
    assert validated.to_dict() == {"first": "shared-label", "second": "shared-label"}


def test_validate_event_details_accepts_safe_payload() -> None:
    validated = validate_event_details({"phase": "validate", "steps": [{"name": "auth"}]})
    assert isinstance(validated, SafeEventDetails)
    assert validated.to_dict() == {"phase": "validate", "steps": [{"name": "auth"}]}


def test_validate_event_details_deep_copies_input() -> None:
    original = {"phase": "validate", "nested": {"count": 1}}
    validated = validate_event_details(original)
    original["phase"] = "mutated"
    original["nested"]["count"] = 99
    assert validated.to_dict() == {"phase": "validate", "nested": {"count": 1}}


def test_safe_event_details_copy_is_independent_after_validation() -> None:
    original = {"phase": "validate"}
    validated = validate_event_details(original)
    stored = validated.to_dict()
    stored["phase"] = "changed"
    assert validated.to_dict() == {"phase": "validate"}


def test_safe_event_details_direct_construction_is_rejected() -> None:
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed") as exc_info:
        SafeEventDetails(_payload={"password": _SECRET_VALUE})
    _assert_generic_unsafe_error(exc_info)


def test_safe_event_details_repr_is_redacted() -> None:
    validated = validate_event_details({"phase": "validate"})
    assert repr(validated) == "SafeEventDetails(redacted)"
    assert "validate" not in repr(validated)
