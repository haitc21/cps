"""Canonical message envelope fixtures must validate against Pydantic and JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator

from cps.contracts.messages.envelope import MessageEnvelope, assert_supported_major

ROOT = Path(__file__).resolve().parents[2] / "src" / "cps" / "contracts"
FIXTURES = ROOT / "fixtures"
SCHEMA_PATH = ROOT / "jsonschema" / "message_envelope.schema.json"
FIXTURE_PATHS = (
    FIXTURES / "commands" / "connection_validate.json",
    FIXTURES / "events" / "operation_progress.json",
    FIXTURES / "events" / "operation_completed.json",
    FIXTURES / "events" / "operation_failed.json",
    FIXTURES / "events" / "inventory_batch.json",
)


def _schema_validator() -> Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_every_fixture_validates_with_pydantic_and_jsonschema(fixture_path: Path) -> None:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    MessageEnvelope.model_validate(raw)
    _schema_validator().validate(raw)


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS)
def test_fixtures_have_no_inline_secrets(fixture_path: Path) -> None:
    text = fixture_path.read_text(encoding="utf-8").lower()
    for forbidden in ("password", "token", "authorization", "user_data", "private_key"):
        assert forbidden not in text


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS[1:])
def test_events_omit_credential_reference(fixture_path: Path) -> None:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert "credential_reference" not in raw


def test_command_contains_credential_reference() -> None:
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    assert raw["credential_reference"] == "66666666-6666-4666-8666-666666666666"


def test_unknown_major_rejected_and_unknown_minor_field_accepted() -> None:
    with pytest.raises(ValueError, match="unsupported major"):
        assert_supported_major("2.0")
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    raw["future_minor_field"] = {"safe": True}
    MessageEnvelope.model_validate(raw)


def test_jsonschema_rejects_invalid_uuid() -> None:
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    raw["message_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        _schema_validator().validate(raw)


def test_jsonschema_rejects_invalid_datetime() -> None:
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    raw["occurred_at"] = "not-a-datetime"
    with pytest.raises(ValidationError):
        _schema_validator().validate(raw)


def test_naive_occurred_at_rejected() -> None:
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    raw["occurred_at"] = "2026-07-17T00:00:00"
    with pytest.raises(ValueError, match="UTC"):
        MessageEnvelope.model_validate(raw)


def test_non_utc_offset_occurred_at_rejected() -> None:
    raw = json.loads(FIXTURE_PATHS[0].read_text(encoding="utf-8"))
    raw["occurred_at"] = "2026-07-17T00:00:00+07:00"
    with pytest.raises(ValueError, match="UTC"):
        MessageEnvelope.model_validate(raw)
