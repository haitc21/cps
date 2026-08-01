import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from cps.contracts.messages.flavor_operations import (
    FlavorAccessReplaceRequest,
    FlavorCreateRequest,
    FlavorDeleteRequest,
    FlavorExtraSpecsPatchRequest,
)
from cps.contracts.semantic import validate_flavor_operation_document


def _base_create(**changes):
    value = {
        "operation_id": uuid4(),
        "provider_connection_id": uuid4(),
        "name": " small ",
        "vcpus": 1,
        "ram_mib": 512,
        "root_disk_gib": 0,
        "is_public": False,
        "access_project_ids": ["project-b", "project-a"],
    }
    value.update(changes)
    return value


def test_create_normalizes_auto_and_transport_order():
    request = FlavorCreateRequest.model_validate(_base_create(provider_resource_id="auto"))
    assert request.name == "small"
    assert request.provider_resource_id is None
    assert request.access_project_ids == ["project-a", "project-b"]


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"provider_resource_id": "bad/id"},
        {"vcpus": True},
        {"vcpus": 0},
        {"ram_mib": 16_777_217},
        {"is_public": True},
        {"access_project_ids": ["project-a", "project-a"]},
        {"extra_specs": {"admin_password": "synthetic"}},  # pragma: allowlist secret
        {"extra_specs": {"safe": "bearer token"}},
        {"unexpected": True},
    ],
)
def test_create_rejects_invalid_or_unsafe_values(changes):
    with pytest.raises(ValidationError):
        FlavorCreateRequest.model_validate(_base_create(**changes))


def test_public_create_requires_empty_access():
    request = FlavorCreateRequest.model_validate(
        _base_create(is_public=True, access_project_ids=[])
    )
    assert request.is_public is True


def test_access_replace_is_unique_bounded_and_canonical():
    request = FlavorAccessReplaceRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        provider_resource_id="flavor-1",
        project_provider_resource_ids=["project-b", "project-a"],
    )
    assert request.project_provider_resource_ids == ["project-a", "project-b"]
    with pytest.raises(ValidationError):
        request.model_copy(update={"project_provider_resource_ids": ["x", "x"]}).model_validate(
            request.model_copy(update={"project_provider_resource_ids": ["x", "x"]}).model_dump()
        )


def test_extra_specs_patch_requires_disjoint_nonempty_changes():
    request = FlavorExtraSpecsPatchRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        provider_resource_id="flavor-1",
        set={"hw:cpu_policy": "shared"},
        unset=["old"],
    )
    assert request.set == {"hw:cpu_policy": "shared"}
    for payload in ({}, {"set": {"same": "x"}, "unset": ["same"]}):
        with pytest.raises(ValidationError):
            FlavorExtraSpecsPatchRequest(
                operation_id=uuid4(),
                provider_connection_id=uuid4(),
                provider_resource_id="flavor-1",
                **payload,
            )


def test_delete_requires_provider_identity():
    with pytest.raises(ValidationError):
        FlavorDeleteRequest(
            operation_id=uuid4(), provider_connection_id=uuid4(), provider_resource_id=""
        )


def test_json_schema_locks_variant_fields_and_matches_runtime():
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "src/cps/contracts/jsonschema/flavor_operation.schema.json"
    )
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    valid = FlavorCreateRequest.model_validate(_base_create()).model_dump(mode="json")
    validator.validate(valid)
    invalid_cases = [
        {key: value for key, value in valid.items() if key != "ram_mib"},
        {**valid, "unset": ["not-a-create-field"]},
        {**valid, "schema_version": "2.0"},
    ]
    for invalid in invalid_cases:
        assert list(validator.iter_errors(invalid))
        with pytest.raises(ValidationError):
            FlavorCreateRequest.model_validate(invalid)


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "delete", "provider_resource_id": "bad/id"},
        {
            "operation": "extra_specs.patch",
            "provider_resource_id": "flavor-1",
            "set": {"admin_password": "value"},  # pragma: allowlist secret
            "unset": [],
        },
        {
            "operation": "extra_specs.patch",
            "provider_resource_id": "flavor-1",
            "set": {"safe": "Bearer abcdefgh1"},
            "unset": [],
        },
        {
            "operation": "extra_specs.patch",
            "provider_resource_id": "flavor-1",
            "set": {"same": "value"},
            "unset": ["same"],
        },
    ],
)
def test_canonical_schema_validation_rejects_runtime_invalid_matrix(payload):
    raw = {
        "schema_version": "1.0",
        "operation_id": str(uuid4()),
        "provider_connection_id": str(uuid4()),
        "required_scope": "SYSTEM",
        "resource_type": "flavor",
        **payload,
    }
    with pytest.raises((ValidationError, ValueError, JsonSchemaValidationError)):
        validate_flavor_operation_document(
            Path(__file__).resolve().parents[2] / "src/cps/contracts", raw
        )
