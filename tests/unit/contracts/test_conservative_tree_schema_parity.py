"""Bidirectional parity between conservative tree runtime and inventory JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from cps.contracts.messages.inventory import InventoryBatchPayload, compute_inventory_checksum

ROOT = Path(__file__).parents[3] / "src/cps/contracts"


def _item_schema_validator() -> tuple[Draft202012Validator, type[JsonSchemaValidationError]]:
    schema = json.loads((ROOT / "jsonschema/inventory_batch.schema.json").read_text())
    item_schema = {**schema["$defs"]["InventoryBatchItem"], "$defs": schema["$defs"]}
    return Draft202012Validator(item_schema), JsonSchemaValidationError


def _batch(resource_type: str, item: dict[str, object]) -> dict[str, object]:
    return {
        "sync_id": "77777777-7777-4777-8777-777777777777",
        "resource_type": resource_type,
        "sequence": 1,
        "is_last": True,
        "collection_status": "COMPLETE",
        "item_count": 1,
        "checksum": compute_inventory_checksum([item]),
        "items": [item],
    }


def _envelope(payload: dict[str, object]) -> dict[str, object]:
    return {
        "message_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "message_type": "cloud.inventory.batch",
        "schema_version": "1.1",
        "occurred_at": "2026-08-01T00:00:00Z",
        "correlation_id": "22222222-2222-4222-8222-222222222222",
        "causation_id": "11111111-1111-4111-8111-111111111111",
        "operation_id": "33333333-3333-4333-8333-333333333333",
        "idempotency_key": None,
        "provider_id": "44444444-4444-4444-8444-444444444444",
        "provider_connection_id": "55555555-5555-4555-8555-555555555555",
        "trace_context": {},
        "payload": payload,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metadata", {"nested": {"paths": [["nested-in-list"]]}}),
        ("attachments", [{"paths": [["nested-in-list"]]}]),
        (
            "attributes",
            {"catalog_approved": True, "properties": {"nested": {"paths": [["nested-in-list"]]}}},
        ),
    ],
)
def test_runtime_and_schema_both_reject_nested_structures_in_lists(
    field: str, value: object
) -> None:
    item: dict[str, object] = {
        "provider_resource_id": "x",
        "name": "x",
    }
    if field == "attributes":
        item["attributes"] = value
    else:
        item[field] = value
    validator, json_schema_error = _item_schema_validator()
    with pytest.raises((ValidationError, ValueError)):
        InventoryBatchPayload.model_validate(_batch("image", item))
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_runtime_and_schema_both_accept_root_metadata_with_many_scalar_entries() -> None:
    metadata = {f"k{i}": f"v{i}" for i in range(128)}
    item = {"provider_resource_id": "x", "name": "x", "metadata": metadata}
    validator, _ = _item_schema_validator()
    InventoryBatchPayload.model_validate(_batch("volume", item))
    validator.validate(item)


def test_runtime_and_schema_both_reject_root_metadata_exceeding_128_entries() -> None:
    metadata = {f"k{i}": f"v{i}" for i in range(129)}
    item = {"provider_resource_id": "x", "name": "x", "metadata": metadata}
    validator, json_schema_error = _item_schema_validator()
    with pytest.raises((ValidationError, ValueError)):
        InventoryBatchPayload.model_validate(_batch("volume", item))
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_catalog_string_255_accepted_by_runtime_and_schema() -> None:
    long_value = "a" * 200
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {
            "catalog_approved": True,
            "container_format": long_value,
            "tags": [long_value],
        },
    }
    validator, _ = _item_schema_validator()
    InventoryBatchPayload.model_validate(_batch("image", item))
    validator.validate(item)


@pytest.mark.parametrize("fixture_name", [
    "inventory_batch_image_full.json",
    "inventory_batch_image_minimal.json",
    "inventory_batch_flavor_full.json",
    "inventory_batch_flavor_minimal.json",
])
def test_catalog_inventory_fixtures_pass_item_json_schema(fixture_name: str) -> None:
    raw = json.loads((ROOT / "fixtures/events" / fixture_name).read_text())
    payload = raw["payload"]
    validator, _ = _item_schema_validator()
    for item in payload["items"]:
        validator.validate(item)


def _attachment_key(index: int) -> str:
    suffix = str(index)
    return ("k" * (32 - len(suffix))) + suffix


def _worst_case_attachment(
    *,
    depth: int = 0,
    max_depth: int = 3,
    leaf_string_length: int = 128,
) -> dict[str, object]:
    """Deterministic schema-valid attachment through AttachmentDepth4 leaf tier."""
    if depth >= max_depth:
        filler = "v" * leaf_string_length
        return {_attachment_key(index): filler for index in range(4)}
    return {
        _attachment_key(index): _worst_case_attachment(
            depth=depth + 1,
            max_depth=max_depth,
            leaf_string_length=leaf_string_length,
        )
        for index in range(4)
    }


def test_worst_case_schema_valid_attachment_serializes_below_64_kib() -> None:
    from cps.contracts.safe_metadata import MAX_ATTACHMENT_SERIALIZED_BYTES

    attachment = _worst_case_attachment()
    serialized = json.dumps([attachment], separators=(",", ":"), sort_keys=True).encode()
    assert len(serialized) < MAX_ATTACHMENT_SERIALIZED_BYTES
    validator, _ = _item_schema_validator()
    item = {"provider_resource_id": "vol-1", "name": "data", "attachments": [attachment]}
    InventoryBatchPayload.model_validate(_batch("volume", item))
    validator.validate(item)


def test_worst_case_schema_valid_attachments_at_max_items_stays_below_64_kib() -> None:
    from cps.contracts.safe_metadata import MAX_ATTACHMENT_OBJECTS, MAX_ATTACHMENT_SERIALIZED_BYTES

    shallow = {_attachment_key(index): "v" * 120 for index in range(4)}
    attachments = [shallow for _ in range(MAX_ATTACHMENT_OBJECTS)]
    serialized = json.dumps(attachments, separators=(",", ":"), sort_keys=True).encode()
    assert len(attachments) == MAX_ATTACHMENT_OBJECTS
    assert len(serialized) < MAX_ATTACHMENT_SERIALIZED_BYTES
    validator, _ = _item_schema_validator()
    item = {"provider_resource_id": "vol-1", "name": "data", "attachments": attachments}
    InventoryBatchPayload.model_validate(_batch("volume", item))
    validator.validate(item)


def test_runtime_and_schema_both_reject_attributes_root_exceeding_128_entries() -> None:
    attributes = {f"extra_{index}": index for index in range(129)}
    attributes["catalog_approved"] = True
    item = {"provider_resource_id": "x", "name": "x", "attributes": attributes}
    validator, json_schema_error = _item_schema_validator()
    with pytest.raises((ValidationError, ValueError)):
        InventoryBatchPayload.model_validate(_batch("image", item))
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_runtime_and_schema_both_reject_attachment_root_exceeding_4_entries() -> None:
    attachment = {f"k{i}": f"v{i}" for i in range(5)}
    item = {"provider_resource_id": "x", "name": "x", "attachments": [attachment]}
    validator, json_schema_error = _item_schema_validator()
    with pytest.raises((ValidationError, ValueError)):
        InventoryBatchPayload.model_validate(_batch("volume", item))
    with pytest.raises(json_schema_error):
        validator.validate(item)


def _capability_validator() -> tuple[Draft202012Validator, type[JsonSchemaValidationError]]:
    schema = json.loads((ROOT / "jsonschema/capability_document.schema.json").read_text())
    return Draft202012Validator(schema), JsonSchemaValidationError


def _capability_document_base() -> dict[str, object]:
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
            "image.import": {"supported": True},
            "image.member": {"supported": True},
            "image.deactivate": {"supported": True},
            "image.reactivate": {"supported": True},
            "flavor.create": {"supported": True},
            "flavor.delete": {"supported": True},
            "flavor.access": {"supported": True},
            "flavor.extra_specs": {"supported": True},
        },
    }


def _four_level_compute_extra() -> dict[str, object]:
    return {"l1": {"l2": {"l3": {"l4": "leaf"}}}}


def test_capability_runtime_and_schema_both_accept_services_compute_extra_four_levels() -> None:
    from cps.contracts.validation import CapabilityDocument

    document = _capability_document_base()
    document["services"]["compute"]["extra"] = _four_level_compute_extra()  # type: ignore[index]
    validator, _ = _capability_validator()
    CapabilityDocument.model_validate(document)
    validator.validate(document)


def test_capability_runtime_and_schema_both_reject_services_compute_extra_five_levels() -> None:
    from cps.contracts.validation import CapabilityDocument

    document = _capability_document_base()
    document["services"]["compute"]["extra"] = {  # type: ignore[index]
        "l1": {"l2": {"l3": {"l4": {"l5": "too-deep"}}}},
    }
    validator, json_schema_error = _capability_validator()
    with pytest.raises((ValidationError, ValueError)):
        CapabilityDocument.model_validate(document)
    with pytest.raises(json_schema_error):
        validator.validate(document)


def test_capability_runtime_and_schema_both_reject_nested_map_in_extra_list() -> None:
    from cps.contracts.validation import CapabilityDocument

    document: dict[str, object] = {
        "schema_version": "1.1",
        "services": {
            "identity": {"available": True},
            "compute": {"available": True},
            "network": {"available": True},
            "image": {"available": True, "extra": {"tags": [{"nested": "map"}]}},
            "block_storage": {"available": True},
        },
        "features": {
            "connection.authenticate": {"supported": True},
            "service.identity": {"supported": True},
            "service.compute": {"supported": True},
            "service.network": {"supported": True},
            "service.image": {"supported": True},
            "service.block_storage": {"supported": True},
            "image.import": {"supported": True},
            "image.member": {"supported": True},
            "image.deactivate": {"supported": True},
            "image.reactivate": {"supported": True},
            "flavor.create": {"supported": True},
            "flavor.delete": {"supported": True},
            "flavor.access": {"supported": True},
            "flavor.extra_specs": {"supported": True},
        },
    }
    validator, json_schema_error = _capability_validator()
    with pytest.raises((ValidationError, ValueError)):
        CapabilityDocument.model_validate(document)
    with pytest.raises(json_schema_error):
        validator.validate(document)
