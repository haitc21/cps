"""Executable contract tests for the Sprint 2 validation slice."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from cps.contracts.validation import (
    CapabilityDocument,
    CredentialResolution,
    validate_validation_event,
)

ROOT = Path(__file__).parents[2] / "src/cps/contracts"
COMPLETED = ROOT / "fixtures/events/operation_completed.json"
PROGRESS = ROOT / "fixtures/events/operation_progress.json"


def _fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_capability_document_accepts_additive_minor_fields() -> None:
    value = {
        "schema_version": "1.1",
        "services": {
            "identity": {"available": True},
            "compute": {"available": True, "min_version": "2.1", "max_version": "2.90"},
            "network": {"available": True},
            "image": {"available": True},
            "block_storage": {"available": True},
        },
        "features": {
            "connection.authenticate": {"supported": True},
            "service.identity": {"supported": True},
            "service.compute": {"supported": True},
            "service.network": {"supported": True},
            "service.image": {"supported": True},
            "service.block_storage": {"supported": True},
        },
        "future_field": "ignored by older consumers",
    }

    assert CapabilityDocument.model_validate(value).schema_version == "1.1"


@pytest.mark.parametrize("version", ["2.0", "0.1", "bad"])
def test_capability_document_rejects_unknown_major(version: str) -> None:
    with pytest.raises(ValidationError):
        CapabilityDocument.model_validate({"schema_version": version})


def test_capability_document_rejects_secret_and_oversized_payload() -> None:
    value = {
        "schema_version": "1.0",
        "services": {},
        "features": {},
        "password": "never serialize this",
    }
    with pytest.raises(ValidationError):
        CapabilityDocument.model_validate(value)

    oversized = {"schema_version": "1.0", "services": {}, "features": {}, "x": "a" * 65536}
    with pytest.raises(ValidationError):
        CapabilityDocument.model_validate(oversized)


def test_credential_resolution_is_internal_and_bounded() -> None:
    value = {
        "schema_version": "1.0",
        "auth_url": "https://identity.example/v3",
        "username": "synthetic-user",
        "password": "synthetic-password",
        "user_domain_name": "Default",
        "project_name": "synthetic-project",
        "project_domain_name": "Default",
        "region_name": "RegionOne",
        "interface": "public",
        "verify_tls": True,
    }
    resolved = CredentialResolution.model_validate(value)
    assert resolved.password == "synthetic-password"


def test_validation_fixtures_use_safe_payloads() -> None:
    progress = _fixture(PROGRESS)
    completed = _fixture(COMPLETED)
    assert validate_validation_event(progress)
    assert validate_validation_event(completed)
    assert "credential_reference" not in progress
    assert "credential_reference" not in completed


def test_validation_event_rejects_credential_reference_and_raw_provider_payload() -> None:
    progress = _fixture(PROGRESS)
    progress["credential_reference"] = "66666666-6666-4666-8666-666666666666"
    with pytest.raises(ValueError):
        validate_validation_event(progress)

    completed = _fixture(COMPLETED)
    payload = deepcopy(completed["payload"])
    assert isinstance(payload, dict)
    result = payload["result"]
    assert isinstance(result, dict)
    capabilities = result["capabilities"]
    assert isinstance(capabilities, dict)
    capabilities["raw_catalog"] = {"secret": "provider response"}
    payload["result"] = result
    completed["payload"] = payload
    with pytest.raises(ValidationError):
        validate_validation_event(completed)
