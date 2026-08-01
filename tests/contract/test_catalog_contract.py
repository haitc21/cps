import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cps.api.schemas.catalog import CatalogResourceType
from cps.contracts.validation import CapabilityDocument

ROOT = Path(__file__).parents[2] / "src/cps/contracts"


def test_catalog_contract_is_read_only_and_allowlisted() -> None:
    assert {item.value for item in CatalogResourceType} == {
        "image",
        "flavor",
        "network",
        "volume-type",
        "availability-zone",
    }


_CATALOG_CAPABILITY_KEYS = frozenset(
    {
        "image.import",
        "image.member",
        "image.deactivate",
        "image.reactivate",
        "flavor.create",
        "flavor.delete",
        "flavor.access",
        "flavor.extra_specs",
    }
)


def _capability_base() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "services": {
            "identity": {"available": True},
            "compute": {"available": True},
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
    }


def test_capability_document_requires_catalog_administration_keys() -> None:
    value = _capability_base()
    with pytest.raises(ValidationError):
        CapabilityDocument.model_validate(value)
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    doc = CapabilityDocument.model_validate(value)
    assert doc.schema_version == "1.1"


def test_inventory_batch_schema_file_exists() -> None:
    schema_path = ROOT / "jsonschema/inventory_batch.schema.json"
    assert schema_path.is_file(), "inventory_batch.schema.json must exist"


def test_image_full_fixture_validates_against_envelope() -> None:
    fixture_path = ROOT / "fixtures/events/inventory_batch_image_full.json"
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.1"
    assert raw["payload"]["resource_type"] == "image"


def test_capability_document_schema_requires_catalog_keys_for_minor_1_and_above() -> None:
    schema = json.loads((ROOT / "jsonschema/capability_document.schema.json").read_text())
    version_pattern = schema["properties"]["schema_version"].get("pattern")
    assert version_pattern == "^1\\.[0-9]+$"
    all_of = schema.get("allOf", [])
    assert any(
        rule.get("if", {})
        .get("properties", {})
        .get("schema_version", {})
        .get("pattern")
        == "^1\\.0*[1-9][0-9]*$"
        for rule in all_of
    )


def _capability_schema_validator():
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    schema = json.loads((ROOT / "jsonschema/capability_document.schema.json").read_text())
    return Draft202012Validator(schema), JsonSchemaValidationError


def test_capability_json_schema_accepts_1_2_with_catalog_keys() -> None:
    value = _capability_base()
    value["schema_version"] = "1.2"
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    CapabilityDocument.model_validate(value)
    validator, _ = _capability_schema_validator()
    validator.validate(value)


def test_capability_runtime_and_schema_accept_1_01_with_catalog_keys() -> None:
    value = _capability_base()
    value["schema_version"] = "1.01"
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    doc = CapabilityDocument.model_validate(value)
    assert doc.schema_version == "1.01"
    validator, _ = _capability_schema_validator()
    validator.validate(value)


def test_capability_runtime_and_schema_reject_1_01_without_catalog_keys() -> None:
    value = _capability_base()
    value["schema_version"] = "1.01"
    with pytest.raises(ValidationError, match="catalog"):
        CapabilityDocument.model_validate(value)
    validator, json_schema_error = _capability_schema_validator()
    with pytest.raises(json_schema_error):
        validator.validate(value)


@pytest.mark.parametrize("version", ["2.0", "0.1", "bad", "1", "1.x"])
def test_capability_json_schema_rejects_unknown_or_malformed_version(version: str) -> None:
    value = _capability_base()
    value["schema_version"] = version
    validator, json_schema_error = _capability_schema_validator()
    with pytest.raises(json_schema_error):
        validator.validate(value)
    with pytest.raises(ValidationError):
        CapabilityDocument.model_validate(value)


def test_capability_json_schema_requires_base_keys() -> None:
    validator, json_schema_error = _capability_schema_validator()
    with pytest.raises(json_schema_error):
        validator.validate({"schema_version": "1.0"})


def test_capability_json_schema_rejects_secret_key_substrings_in_extra_fields() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["nested_private_key"] = "unsafe"
    with pytest.raises(json_schema_error):
        validator.validate(value)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Bl\n-----END OPENSSH PRIVATE KEY-----",
        "https://storage.example/x?X-Goog-Signature=abc",
        "https://storage.example/x?credential=abc%2F20260801",
    ],
)
def test_capability_json_schema_rejects_pem_and_credential_urls_in_extra_fields(
    unsafe_value: str,
) -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["note"] = unsafe_value
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_json_schema_rejects_unbounded_nested_extra_fields() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["nested"] = {"a": {"b": {"c": {"d": {"e": "too-deep"}}}}}
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_document_runtime_rejects_unbounded_nested_extra_fields() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["nested"] = {"a": {"b": {"c": {"d": {"e": "too-deep"}}}}}
    with pytest.raises(ValidationError, match="depth"):
        CapabilityDocument.model_validate(value)


def test_capability_document_runtime_rejects_oversized_extra_field_maps() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["big"] = {f"k{index}": index for index in range(200)}
    with pytest.raises(ValidationError, match="entries"):
        CapabilityDocument.model_validate(value)


@pytest.mark.parametrize(
    ("path", "unsafe_value"),
    [
        (("services", "compute", "min_version"), "https://example.com?token=abc"),
        (("services", "compute", "max_version"), "https://storage.example/x?X-Goog-Signature=abc"),
        (("features", "service.compute", "reason"), "https://storage.example/x?credential=abc"),
    ],
)
def test_capability_json_schema_rejects_secret_values_in_version_and_reason_fields(
    path: tuple[str, ...],
    unsafe_value: str,
) -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    target: dict[str, object] = value
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[index]
    target[path[-1]] = unsafe_value
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_document_runtime_rejects_secret_values_in_version_and_reason_fields() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["services"]["compute"]["min_version"] = "https://example.com?token=abc"
    with pytest.raises(ValidationError, match="forbidden"):
        CapabilityDocument.model_validate(value)


def test_capability_json_schema_rejects_overlong_min_version() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["services"]["compute"]["min_version"] = "v" * 65
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_document_runtime_rejects_overlong_min_version() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["services"]["compute"]["min_version"] = "v" * 65
    with pytest.raises(ValidationError, match="maximum length"):
        CapabilityDocument.model_validate(value)


def test_capability_json_schema_rejects_oversized_serialized_document() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["pad"] = "x" * 2049
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_document_runtime_rejects_more_than_128_services() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    for index in range(124):
        value["services"][f"extra-{index}"] = {"available": True}  # type: ignore[index]
    with pytest.raises(ValidationError, match="services"):
        CapabilityDocument.model_validate(value)


def test_capability_document_runtime_rejects_more_than_128_features() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    for index in range(130):
        value["features"][f"extra-feature-{index}"] = {"supported": False}  # type: ignore[index]
    with pytest.raises(ValidationError, match="features"):
        CapabilityDocument.model_validate(value)


def test_capability_json_schema_rejects_overlong_schema_version() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["schema_version"] = "1." + ("9" * 32)
    with pytest.raises(json_schema_error):
        validator.validate(value)


def test_capability_document_runtime_rejects_overlong_schema_version() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["schema_version"] = "1." + ("9" * 32)
    with pytest.raises(ValidationError, match="schema_version"):
        CapabilityDocument.model_validate(value)


def test_capability_document_runtime_rejects_loose_boolean_scalars() -> None:
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["services"]["identity"] = {"available": 1}  # type: ignore[index]
    with pytest.raises(ValidationError, match="available"):
        CapabilityDocument.model_validate(value)


def test_capability_json_schema_rejects_loose_boolean_scalars() -> None:
    validator, json_schema_error = _capability_schema_validator()
    value = _capability_base()
    for key in _CATALOG_CAPABILITY_KEYS:
        value["features"][key] = {"supported": True}  # type: ignore[index]
    value["features"]["connection.authenticate"] = {"supported": 1}  # type: ignore[index]
    with pytest.raises(json_schema_error):
        validator.validate(value)
