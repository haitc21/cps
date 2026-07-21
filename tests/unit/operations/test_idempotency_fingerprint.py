"""CPS-105 Task 5: canonical request fingerprint unit tests."""

from __future__ import annotations

import math

import pytest

from cps.domain.operations.idempotency import InvalidFingerprintPayloadError, canonical_fingerprint


def test_fingerprint_is_invariant_to_top_level_key_order() -> None:
    first = {"region": "RegionOne", "project": "demo"}
    second = {"project": "demo", "region": "RegionOne"}
    assert canonical_fingerprint(first) == canonical_fingerprint(second)


def test_fingerprint_is_invariant_to_nested_key_order() -> None:
    first = {"outer": {"b": 2, "a": 1}, "z": 9}
    second = {"z": 9, "outer": {"a": 1, "b": 2}}
    assert canonical_fingerprint(first) == canonical_fingerprint(second)


def test_different_payloads_produce_different_fingerprints() -> None:
    assert canonical_fingerprint({"action": "validate"}) != canonical_fingerprint(
        {"action": "create"}
    )


def test_fingerprint_is_sha256_hex() -> None:
    fingerprint = canonical_fingerprint({"action": "validate"})
    assert len(fingerprint) == 64
    assert all(char in "0123456789abcdef" for char in fingerprint)


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
    ],
)
def test_non_finite_values_are_rejected(payload: dict[str, float]) -> None:
    with pytest.raises(InvalidFingerprintPayloadError, match="not fingerprintable"):
        canonical_fingerprint(payload)


def test_invalid_fingerprint_error_does_not_include_payload() -> None:
    payload = {"secret": "super-sensitive-value"}  # pragma: allowlist secret
    with pytest.raises(InvalidFingerprintPayloadError) as exc_info:
        canonical_fingerprint({**payload, "value": math.nan})
    rendered = str(exc_info.value)
    assert "super-sensitive-value" not in rendered
    assert "nan" not in rendered.lower()
