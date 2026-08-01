"""CPS-302 inventory batch contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from cps.contracts.messages.inventory import (
    InventoryBatchItem,
    InventoryBatchPayload,
    InventoryResourceType,
    compute_inventory_checksum,
    compute_inventory_checksum_v1_0,
    compute_inventory_checksum_v1_1,
)


def test_catalog_inventory_resource_types_are_canonical() -> None:
    assert InventoryResourceType.AVAILABILITY_ZONE.value == "availability-zone"
    assert InventoryResourceType.VOLUME_TYPE.value == "volume-type"


def _item() -> dict[str, object]:
    return {
        "provider_resource_id": "server-1",
        "name": "demo",
        "provider_status": "ACTIVE",
        "attributes": {"power_state": "RUNNING"},
    }


def _payload(**overrides: object) -> dict[str, object]:
    items = [_item()]
    value: dict[str, object] = {
        "sync_id": "77777777-7777-4777-8777-777777777777",
        "resource_type": "instance",
        "sequence": 1,
        "is_last": True,
        "collection_status": "COMPLETE",
        "item_count": len(items),
        "checksum": compute_inventory_checksum(items),
        "items": items,
    }
    value.update(overrides)
    return value


def test_inventory_batch_validates_and_checksum_is_deterministic() -> None:
    payload = InventoryBatchPayload.model_validate(_payload())
    assert payload.resource_type is InventoryResourceType.INSTANCE
    assert payload.item_count == 1
    assert UUID(str(payload.sync_id))


def test_legacy_schema_1_0_fixture_accepts_v1_0_checksum() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "src/cps/contracts/fixtures/events/inventory_batch.json"
        ).read_text(encoding="utf-8")
    )
    InventoryBatchPayload.model_validate(
        fixture["payload"],
        context={"schema_version": fixture["schema_version"]},
    )


def test_schema_1_0_envelope_rejects_mismatched_legacy_checksum() -> None:
    with pytest.raises(ValidationError, match="checksum"):
        InventoryBatchPayload.model_validate(
            _payload(checksum="0" * 64),
            context={"schema_version": "1.0"},
        )


def test_schema_1_1_checksum_is_deterministic_and_distinct_from_wrong_digest() -> None:
    items = [_item()]
    payload = InventoryBatchPayload.model_validate(_payload(items=items, item_count=1))
    assert payload.checksum == compute_inventory_checksum_v1_1(payload.items)
    with pytest.raises(ValidationError, match="checksum"):
        InventoryBatchPayload.model_validate(
            _payload(items=items, item_count=1, checksum="0" * 64),
            context={"schema_version": "1.1"},
        )


def test_legacy_checksum_cannot_bypass_1_1_safety_validation() -> None:
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"password": "secret"},
    }
    with pytest.raises(ValidationError, match="forbidden"):
        InventoryBatchPayload.model_validate(
            _batch_payload("image", [item]),
            context={"schema_version": "1.0"},
        )


def test_schema_1_0_envelope_rejects_enriched_items_with_valid_checksum() -> None:
    item = {
        "provider_resource_id": "img-1",
        "name": "catalog",
        "provider_status": "active",
        "visibility": "public",
        "disk_format": "qcow2",
        "attributes": {"catalog_approved": True},
    }
    parsed_item = InventoryBatchItem.model_validate(item)
    checksum = compute_inventory_checksum_v1_0([parsed_item])
    with pytest.raises(ValidationError, match="schema version 1.0"):
        InventoryBatchPayload.model_validate(
            {
                "sync_id": "77777777-7777-4777-8777-777777777777",
                "resource_type": "image",
                "sequence": 1,
                "is_last": True,
                "collection_status": "COMPLETE",
                "item_count": 1,
                "checksum": checksum,
                "items": [item],
            },
            context={"schema_version": "1.0"},
        )


def test_schema_1_1_envelope_rejects_mismatched_checksum_algorithm() -> None:
    item = {
        "provider_resource_id": "img-1",
        "name": "catalog",
        "provider_status": "active",
        "visibility": "public",
        "disk_format": "qcow2",
        "attributes": {"catalog_approved": True},
    }
    with pytest.raises(ValidationError, match="checksum"):
        InventoryBatchPayload.model_validate(
            {**_batch_payload("image", [item]), "checksum": "0" * 64},
            context={"schema_version": "1.1"},
        )


@pytest.mark.parametrize(
    "item_override",
    [
        {"visibility": "public"},
        {"disk_format": "qcow2"},
        {"vcpus": 2},
        {"attributes": {"catalog_approved": True}},
        {"attributes": {"tags": ["approved"]}},
        {"provider_created_at": "2026-08-01T00:00:00Z"},
    ],
)
def test_schema_1_0_envelope_rejects_catalog_1_1_fields(item_override: dict[str, object]) -> None:
    base = {
        "provider_resource_id": "x",
        "name": "legacy",
        "provider_status": "ACTIVE",
    }
    base.update(item_override)
    with pytest.raises(ValidationError, match="schema version 1.0"):
        InventoryBatchPayload.model_validate(
            _batch_payload("image", [base]),
            context={"schema_version": "1.0"},
        )


@pytest.mark.parametrize(
    "override,match",
    [
        ({"checksum": "0" * 64}, "checksum"),
        ({"item_count": 2}, "item_count"),
        ({"sequence": 0}, "sequence"),
        ({"resource_type": "unknown"}, "resource_type"),
    ],
)
def test_inventory_batch_rejects_integrity_errors(override: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(_payload(**override))


def test_unsupported_collection_is_explicit_and_must_be_empty() -> None:
    payload = InventoryBatchPayload.model_validate(
        _payload(
            collection_status="SKIPPED_UNSUPPORTED",
            items=[],
            item_count=0,
            checksum=compute_inventory_checksum([]),
        )
    )
    assert payload.collection_status == "SKIPPED_UNSUPPORTED"
    with pytest.raises(ValidationError, match="unsupported collection"):
        InventoryBatchPayload.model_validate(_payload(collection_status="SKIPPED_UNSUPPORTED"))


def test_volume_batch_accepts_typed_inventory_fields() -> None:
    item = {
        "provider_resource_id": "volume-1",
        "project_provider_resource_id": "project-1",
        "name": "data",
        "provider_status": "available",
        "size_gib": 20,
        "volume_type_provider_resource_id": "fast-1",
        "bootable": False,
        "root": False,
        "encrypted": True,
        "metadata": {"tier": "gold"},
        "availability_zone": "nova",
        "attachments": [{"server_id": "server-1", "device": "/dev/vdb"}],
    }
    payload = InventoryBatchPayload.model_validate(
        _payload(
            resource_type="volume",
            items=[item],
            item_count=1,
            checksum=compute_inventory_checksum([item]),
        )
    )

    assert payload.items[0].size_gib == 20
    assert payload.items[0].volume_type_provider_resource_id == "fast-1"
    assert payload.items[0].attachments == [{"server_id": "server-1", "device": "/dev/vdb"}]


def test_volume_snapshot_batch_accepts_typed_inventory_fields() -> None:
    item = {
        "provider_resource_id": "snapshot-1",
        "project_provider_resource_id": "project-1",
        "name": "before-upgrade",
        "provider_status": "available",
        "volume_provider_resource_id": "volume-1",
        "snapshot_size_gib": 20,
        "metadata": {"tier": "gold"},
    }
    payload = InventoryBatchPayload.model_validate(
        _payload(
            resource_type="volume-snapshot",
            items=[item],
            item_count=1,
            checksum=compute_inventory_checksum([item]),
        )
    )
    assert payload.resource_type is InventoryResourceType.VOLUME_SNAPSHOT
    assert payload.items[0].volume_provider_resource_id == "volume-1"


def _batch_payload(resource_type: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "sync_id": "77777777-7777-4777-8777-777777777777",
        "resource_type": resource_type,
        "sequence": 1,
        "is_last": True,
        "collection_status": "COMPLETE",
        "item_count": len(items),
        "checksum": compute_inventory_checksum(items),
        "items": items,
    }


def test_image_batch_full_fixture_fields_validate() -> None:
    item = {
        "provider_resource_id": "img-full-1",
        "name": "ubuntu-22.04",
        "provider_status": "active",
        "project_provider_resource_id": "project-1",
        "visibility": "public",
        "size_bytes": 2_147_483_648,
        "min_disk_gib": 20,
        "min_ram_mib": 512,
        "disk_format": "qcow2",
        "checksum": "abc123",
        "attributes": {
            "catalog_approved": True,
            "is_protected": False,
            "container_format": "bare",
            "virtual_size_bytes": 2_147_483_648,
            "tags": ["cmp-catalog-approved=true"],
            "properties": {"os_type": "linux"},
            "member_project_ids": ["project-2"],
        },
    }
    payload = InventoryBatchPayload.model_validate(_batch_payload("image", [item]))
    row = payload.items[0]
    assert row.visibility == "public"
    assert row.disk_format == "qcow2"
    assert row.attributes["catalog_approved"] is True


def test_image_batch_minimal_fixture_fields_validate() -> None:
    item = {
        "provider_resource_id": "img-min-1",
        "name": "minimal",
        "provider_status": "active",
    }
    payload = InventoryBatchPayload.model_validate(_batch_payload("image", [item]))
    assert payload.items[0].name == "minimal"


def test_flavor_batch_full_fixture_fields_validate() -> None:
    item = {
        "provider_resource_id": "flv-full-1",
        "name": "m1.small",
        "provider_status": "active",
        "vcpus": 1,
        "ram_mib": 2048,
        "root_disk_gib": 20,
        "ephemeral_disk_gib": 0,
        "swap_mib": 0,
        "is_public": True,
        "enabled": True,
        "attributes": {
            "catalog_approved": True,
            "extra_specs": {"hw:cpu_policy": "shared"},
            "access_project_ids": ["project-1"],
        },
    }
    payload = InventoryBatchPayload.model_validate(_batch_payload("flavor", [item]))
    row = payload.items[0]
    assert row.vcpus == 1
    assert row.ram_mib == 2048
    assert row.is_public is True


def test_flavor_batch_minimal_fixture_fields_validate() -> None:
    item = {
        "provider_resource_id": "flv-min-1",
        "name": "minimal-flavor",
    }
    payload = InventoryBatchPayload.model_validate(_batch_payload("flavor", [item]))
    assert payload.items[0].name == "minimal-flavor"


@pytest.mark.parametrize(
    "visibility",
    ["public", "private", "shared", "community"],
)
def test_image_visibility_enum_accepts_canonical_values(visibility: str) -> None:
    item = {
        "provider_resource_id": "img-vis",
        "name": "vis",
        "visibility": visibility,
    }
    payload = InventoryBatchPayload.model_validate(_batch_payload("image", [item]))
    assert payload.items[0].visibility == visibility


@pytest.mark.parametrize(
    "override,match",
    [
        ({"visibility": "invalid"}, "visibility"),
        ({"size_bytes": -1}, "size_bytes"),
        ({"min_disk_gib": -1}, "min_disk_gib"),
        ({"vcpus": 5000}, "vcpus"),
        (
            {
                "attributes": {
                    "ca_cert_pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
                }
            },
            "forbidden",
        ),
        ({"attributes": {"privateKey": "not-a-key"}}, "forbidden"),
        ({"attributes": {"userData": "cloud-init"}}, "forbidden"),
        ({"attributes": {"rawResponse": {"status": 200}}}, "forbidden"),
        ({"attributes": {"caCertPem": "pem-bytes"}}, "forbidden"),
        ({"metadata": {"nested": {"userData": "secret"}}}, "forbidden"),
        ({"attributes": {"properties": {"nested_private_key": "x"}}}, "forbidden"),
        (
            {
                "metadata": {
                    "tls": "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
                }
            },
            "forbidden",
        ),
        ({"attributes": {"password": "secret"}}, "forbidden"),
        ({"metadata": {"nested": {"token": "secret"}}}, "forbidden"),
        ({"attachments": [{"location": "https://example.com?token=abc"}]}, "forbidden"),
        ({"metadata": {"items": [{"password": "nested"}]}}, "list entry is invalid"),
        ({"attributes": {"properties": [{"token": "in-list"}]}}, "must be an object"),
        ({"attributes": {"password": ["nested-value"]}}, "forbidden"),
        (
            {"attachments": [{"url": "https://storage.example/x?X-Amz-Signature=abc"}]},
            "forbidden",
        ),
        ({"metadata": {"x": "a" * 129}}, "maximum length"),
        ({"attachments": [{"pad": "x" * 129}]}, "maximum length"),
        ({"attributes": {"properties": {"pad": "z" * 129}}}, "maximum length"),
        ({"metadata": {"items": [None]}}, "unsupported scalar"),
    ],
)
def test_catalog_inventory_rejects_invalid_or_secret_fields(
    override: dict[str, object],
    match: str,
) -> None:
    base = {
        "provider_resource_id": "bad-1",
        "name": "bad",
    }
    base.update(override)
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(_batch_payload("image", [base]))


def test_catalog_inventory_accepts_worst_case_attachment_shape_within_structural_bounds() -> None:
    item = {
        "provider_resource_id": "vol-1",
        "name": "data",
        "attachments": [
            {"a": "x" * 128, "b": "x" * 128, "c": "x" * 128, "d": "x" * 128}
            for _ in range(32)
        ],
    }
    InventoryBatchPayload.model_validate(_batch_payload("volume", [item]))


def test_catalog_inventory_accepts_256_access_project_ids() -> None:
    item = {
        "provider_resource_id": "flv-1",
        "name": "large-access",
        "attributes": {
            "catalog_approved": True,
            "access_project_ids": [f"project-{index}" for index in range(256)],
        },
    }
    InventoryBatchPayload.model_validate(_batch_payload("flavor", [item]))


@pytest.mark.parametrize(
    "override,match",
    [
        ({"vcpus": "1"}, "vcpus"),
        ({"bootable": 1}, "bootable"),
        ({"size_bytes": "1024"}, "size_bytes"),
    ],
)
def test_inventory_batch_rejects_loose_typed_scalar_fields(
    override: dict[str, object],
    match: str,
) -> None:
    base = {"provider_resource_id": "x", "name": "x", **override}
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(_batch_payload("image", [base]))


@pytest.mark.parametrize("secret_key", ["signed__url", "private..key"])
def test_catalog_inventory_rejects_separator_variant_secret_keys(secret_key: str) -> None:
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {secret_key: "value"},
    }
    with pytest.raises(ValidationError, match="forbidden"):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_inventory_checksum_rejects_uppercase_disk_format() -> None:
    item = {
        "provider_resource_id": "img-1",
        "name": "x",
        "disk_format": "QCOW2",
    }
    with pytest.raises(ValidationError, match="disk_format"):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_catalog_inventory_rejects_secret_bearing_top_level_string_fields() -> None:
    item = {
        "provider_resource_id": "https://example.com?token=abc",
        "name": "x",
    }
    with pytest.raises(ValidationError, match="forbidden"):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_inventory_json_schema_rejects_uppercase_disk_format() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {"provider_resource_id": "img-1", "name": "x", "disk_format": "QCOW2"}
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_secret_bearing_top_level_catalog_strings() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "https://storage.example/x?X-Amz-Signature=abc",
        "name": "x",
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize("disk_format", ["not-listed", "!"])
def test_catalog_inventory_rejects_non_allowlisted_disk_format(disk_format: str) -> None:
    item = {
        "provider_resource_id": "img-1",
        "name": "x",
        "disk_format": disk_format,
    }
    with pytest.raises(ValidationError, match="disk_format"):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_inventory_json_schema_rejects_non_allowlisted_disk_format() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {"provider_resource_id": "img-1", "name": "x", "disk_format": "not-listed"}
    with pytest.raises(json_schema_error):
        validator.validate(item)


def _inventory_item_json_schema_validator():
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    root = Path(__file__).parents[2] / "src/cps/contracts"
    schema_path = root / "jsonschema/inventory_batch.schema.json"
    schema = json.loads(schema_path.read_text())
    item_schema = {
        **schema["$defs"]["InventoryBatchItem"],
        "$defs": schema["$defs"],
    }
    return Draft202012Validator(item_schema), JsonSchemaValidationError


@pytest.mark.parametrize("secret_key", ["signed__url", "private..key"])
def test_inventory_json_schema_rejects_separator_variant_secret_keys(secret_key: str) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "metadata": {secret_key: "value"},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "https://user:secret@example.com/image",
        "https://example.com/path?signed_url=abc",
    ],
)
def test_inventory_json_schema_rejects_userinfo_and_signed_url_query_values(
    unsafe_value: str,
) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "metadata": {"location": unsafe_value},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_null_attachment_scalar() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "vol-1",
        "name": "data",
        "attachments": [{"device": None}],
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_accepts_256_access_project_ids() -> None:
    validator, _ = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "flv-1",
        "name": "flavor",
        "attributes": {
            "access_project_ids": [f"project-{index}" for index in range(256)],
        },
    }
    validator.validate(item)


def test_inventory_json_schema_rejects_oversized_attachments_array() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attachments": [{"device": f"/dev/vd{i}"} for i in range(33)],
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_secret_bearing_keys() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"privateKey": "placeholder"},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_oversized_attribute_strings() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"properties": {"pad": "z" * 129}},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_camel_case_secret_keys() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    for secret_key in ("userData", "rawResponse", "caCertPem"):
        item = {
            "provider_resource_id": "x",
            "name": "x",
            "metadata": {secret_key: "value"},
        }
        with pytest.raises(json_schema_error):
            validator.validate(item)


@pytest.mark.parametrize(
    "secret_key",
    [
        "nested_private_key",
        "my_token_field",
        "x-authorization-header",
        "stored_user_data",
    ],
)
def test_inventory_json_schema_rejects_secret_key_substring_variants(secret_key: str) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {secret_key: "value"},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    "pem_value",
    [
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----\nMHc\n-----END EC PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Bl\n-----END OPENSSH PRIVATE KEY-----",
    ],
)
def test_inventory_json_schema_rejects_pem_private_key_variants(pem_value: str) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "metadata": {"note": pem_value},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "https://storage.example/x?X-Goog-Signature=abc",
        "https://storage.example/x?credential=abc%2F20260801",
        "https://s3.example/x?AWSAccessKeyId=AKIA123",
    ],
)
def test_inventory_json_schema_rejects_credential_and_signed_urls(unsafe_value: str) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"location": unsafe_value},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize("catalog_approved", ["true", 1, {"approved": True}])
def test_inventory_json_schema_rejects_non_boolean_catalog_approved(
    catalog_approved: object,
) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"catalog_approved": catalog_approved},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    "tags",
    [
        [123, "ok"],
        ["x" * 256],
        [f"tag-{index}" for index in range(65)],
    ],
)
def test_inventory_json_schema_rejects_invalid_tags(tags: list[object]) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"catalog_approved": True, "tags": tags},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    "attributes,match",
    [
        ({"virtual_size_bytes": True}, "virtual_size_bytes"),
        ({"virtual_size_bytes": "1024"}, "virtual_size_bytes"),
        ({"container_format": "x" * 256}, "container_format"),
        ({"is_protected": 1}, "is_protected"),
    ],
)
def test_catalog_inventory_rejects_loose_attribute_scalar_types(
    attributes: dict[str, object],
    match: str,
) -> None:
    base = {
        "provider_resource_id": "bad-1",
        "name": "bad",
        "attributes": attributes,
    }
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(_batch_payload("image", [base]))


def test_catalog_inventory_rejects_conflicting_ownership_sources() -> None:
    item = {
        "provider_resource_id": "img-1",
        "name": "owned",
        "project_provider_resource_id": "project-a",
        "attributes": {"project_id": "project-b"},
    }
    with pytest.raises(ValidationError, match="conflicting ownership sources") as exc_info:
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))
    messages = [error["msg"] for error in exc_info.value.errors()]
    assert messages
    for message in messages:
        assert "project-a" not in message
        assert "project-b" not in message


@pytest.mark.parametrize(
    "secret_key",
    ["credential_ref", "signed_url_field", "my_signed_url_key", "x_credential_y"],
)
def test_catalog_inventory_rejects_credential_and_signed_url_keys(secret_key: str) -> None:
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {secret_key: "value"},
    }
    with pytest.raises(ValidationError, match="forbidden"):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_volume_batch_rejects_non_object_attachment_entries() -> None:
    item = {
        "provider_resource_id": "volume-1",
        "name": "data",
        "attachments": ["not-an-object"],
    }
    with pytest.raises(ValidationError, match="attachment"):
        InventoryBatchPayload.model_validate(
            _batch_payload("volume", [item]),
        )


@pytest.mark.parametrize("secret_key", ["credential_ref", "signed_url_meta"])
def test_inventory_json_schema_rejects_credential_and_signed_url_key_names(
    secret_key: str,
) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "metadata": {secret_key: "value"},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("container_format", "https://storage.example/x?X-Goog-Signature=abc"),
        ("tags", ["https://storage.example/x?credential=abc%2F20260801"]),
        ("access_project_ids", ["https://example.com?token=secret"]),
        (
            "member_project_ids",
            ["-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"],
        ),
    ],
)
def test_inventory_json_schema_rejects_secret_values_in_catalog_attribute_strings(
    field: str,
    unsafe_value: object,
) -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "attributes": {"catalog_approved": True, field: unsafe_value},
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_accepts_scalar_attachment_lists() -> None:
    validator, _ = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "vol-1",
        "name": "data",
        "attachments": [
            {
                "server_id": "srv-1",
                "paths": ["/dev/vdb", "/dev/vdc"],
                "meta": {"zone": "az-1"},
            }
        ],
    }
    validator.validate(item)


def test_inventory_json_schema_rejects_nested_attachment_list_entries() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "vol-1",
        "name": "data",
        "attachments": [{"devices": [["/dev/vdb", "/dev/vdc"]]}],
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_inventory_json_schema_rejects_oversized_attachment_serialized_payload() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "vol-1",
        "name": "data",
        "attachments": [{"pad": "x" * 129} for _ in range(32)],
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("provider_created_at", "not-a-timestamp", "timestamp"),
        ("provider_updated_at", "2026-08-01T00:00:00Z" + ("0" * 40), "timestamp"),
        ("provider_created_at", "password=2026-08-01T00:00:00Z", "forbidden"),
        ("provider_created_at", "2026-02-30T00:00:00Z", "valid ISO-8601"),
        ("provider_updated_at", "2026-08-01T00:00:00+25:00", "ISO-8601 timestamp"),
        ("provider_created_at", "2026-13-01T00:00:00Z", "ISO-8601 timestamp"),
    ],
)
def test_catalog_inventory_rejects_unsafe_or_unbounded_provider_timestamps(
    field: str,
    value: str,
    match: str,
) -> None:
    item = {"provider_resource_id": "x", "name": "x", field: value}
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(_batch_payload("image", [item]))


def test_inventory_json_schema_rejects_unbounded_provider_timestamps() -> None:
    validator, json_schema_error = _inventory_item_json_schema_validator()
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "provider_created_at": "2026-08-01T00:00:00Z" + ("0" * 40),
    }
    with pytest.raises(json_schema_error):
        validator.validate(item)


def test_catalog_inventory_accepts_bounded_provider_timestamps() -> None:
    item = {
        "provider_resource_id": "x",
        "name": "x",
        "provider_created_at": "2026-08-01T00:00:00Z",
        "provider_updated_at": "2026-08-01T12:34:56.123456Z",
    }
    row = InventoryBatchPayload.model_validate(_batch_payload("image", [item])).items[0]
    assert row.provider_created_at == "2026-08-01T00:00:00Z"
    assert row.provider_updated_at == "2026-08-01T12:34:56.123456Z"
