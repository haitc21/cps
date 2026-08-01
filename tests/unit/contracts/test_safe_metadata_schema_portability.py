"""ECMA-262 portability checks for contract JSON Schema patterns."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cps.contracts.safe_metadata import (
    ecma262_secret_key_pattern,
    is_secret_key,
    is_secret_value,
)

ROOT = Path(__file__).parents[3] / "src/cps/contracts/jsonschema"
_INLINE_FLAG = re.compile(r"\(\?[a-zA-Z]+(?::|\))")


def _collect_patterns(node: object) -> list[str]:
    patterns: list[str] = []
    if isinstance(node, dict):
        if "pattern" in node and isinstance(node["pattern"], str):
            patterns.append(node["pattern"])
        for value in node.values():
            patterns.extend(_collect_patterns(value))
    elif isinstance(node, list):
        for item in node:
            patterns.extend(_collect_patterns(item))
    return patterns


@pytest.mark.parametrize(
    "schema_file",
    ["inventory_batch.schema.json", "capability_document.schema.json"],
)
def test_json_schema_patterns_are_ecma262_portable_without_inline_flags(
    schema_file: str,
) -> None:
    schema = json.loads((ROOT / schema_file).read_text(encoding="utf-8"))
    patterns = _collect_patterns(schema)
    assert patterns, f"expected patterns in {schema_file}"
    for pattern in patterns:
        assert _INLINE_FLAG.search(pattern) is None, pattern
        re.compile(pattern)


def test_runtime_and_schema_secret_key_patterns_reject_separator_variants() -> None:
    for key in ("signed__url", "private..key", "user__data"):
        assert is_secret_key(key)
    combined = ecma262_secret_key_pattern()
    for key in ("signed__url", "private..key", "user__data"):
        assert re.search(combined, key)


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://user:secret@example.com/image",
        "https://example.com/path?signed_url=abc",
        "metadata: https://user:secret@example.com/x",
        "see https://example.com/path?token=abc",
        "password=super-secret",
        "export token=abc123",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "authorization: basic dXNlcjpwYXNz",
        "Authorization: Token abcdef0123456789",
        "authorization: token deadbeef01234567",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "Basic dXNlcjpwYXNz",
        "Token abcdef0123456789",
        "Bearer abcdefghijklmnop",
        "Token abcdefghijklmnop",
        "bearer lettersonlycredential",
    ],
)
def test_secret_value_detection_covers_userinfo_and_signed_url_query(unsafe: str) -> None:
    assert is_secret_value(unsafe)


@pytest.mark.parametrize(
    "unsafe",
    [
        "Bearer abcdefghijklmnop",
        "Token abcdefghijklmnop",
        "bearer lettersonlycredential",
        "Bearer abcdefgh ",
        "Token abcdefgh .",
    ],
)
def test_runtime_and_schema_both_reject_letter_only_bearer_or_token_credentials(
    unsafe: str,
) -> None:
    assert is_secret_value(unsafe)
    from cps.contracts.safe_metadata import ecma262_secret_value_patterns

    matched = False
    for pattern in ecma262_secret_value_patterns():
        if re.compile(pattern).search(unsafe):
            matched = True
            break
    assert matched, unsafe


@pytest.mark.parametrize(
    "safe",
    [
        "password_policy_enabled",
        "token_count",
        "authorization_scope",
        "my-authorization-scope",
        "uses bearer authentication conceptually",
        "project-alpha-2026",
    ],
)
def test_secret_value_detection_allows_ordinary_names_without_assignments(safe: str) -> None:
    assert not is_secret_value(safe)


def test_runtime_and_schema_secret_value_patterns_reject_password_token_and_auth_schemes() -> None:
    from cps.contracts.safe_metadata import ecma262_secret_value_patterns

    unsafe_samples = (
        "password=secret",
        "token=abc",
        "Authorization: Bearer token-value",
        "authorization: basic dXNlcjpwYXNz",
    )
    for pattern in ecma262_secret_value_patterns():
        compiled = re.compile(pattern)
        for sample in unsafe_samples:
            if compiled.search(sample):
                break
        else:
            continue
        break
    else:
        pytest.fail("expected at least one schema pattern to match password/token/auth samples")
    for pattern in ecma262_secret_value_patterns():
        compiled = re.compile(pattern)
        for safe in ("password_policy", "token_count", "authorization_scope"):
            assert compiled.search(safe) is None, (pattern, safe)
