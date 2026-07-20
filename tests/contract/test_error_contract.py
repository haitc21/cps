"""Common error fixtures must validate without secrets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator

from cps.contracts.errors import CommonError

ROOT = Path(__file__).resolve().parents[2] / "src" / "cps" / "contracts"
FIXTURE_PATH = ROOT / "fixtures" / "errors" / "provider_authentication_failed.json"
SCHEMA_PATH = ROOT / "jsonschema" / "common_error.schema.json"


def _schema_validator() -> Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_authentication_error_fixture_is_safe() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    error = CommonError.model_validate(raw)
    assert error.code == "PROVIDER_AUTHENTICATION_FAILED"
    assert error.retryable is False
    assert not ({"password", "token", "authorization"} & set(error.details))
    _schema_validator().validate(raw)


def test_common_error_schema_rejects_invalid_datetime() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["occurred_at"] = "not-a-datetime"
    with pytest.raises(ValidationError):
        _schema_validator().validate(raw)
