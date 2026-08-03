"""CPS-302 inventory batch contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from cps.contracts.messages.inventory import (
    InventoryBatchPayload,
    InventoryResourceType,
    compute_inventory_checksum,
)

ROOT = Path(__file__).resolve().parents[2] / "src" / "cps" / "contracts"
INVENTORY_SCHEMA_PATH = ROOT / "jsonschema" / "inventory_batch.schema.json"
CATALOG_FIXTURE_PATHS = (
    ROOT / "fixtures" / "events" / "inventory_batch_image_full.json",
    ROOT / "fixtures" / "events" / "inventory_batch_image_minimal.json",
    ROOT / "fixtures" / "events" / "inventory_batch_flavor_full.json",
    ROOT / "fixtures" / "events" / "inventory_batch_flavor_minimal.json",
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


def test_image_batch_accepts_enriched_catalog_detail_fields() -> None:
    item = {
        "provider_resource_id": "image-1",
        "project_provider_resource_id": "project-1",
        "name": "ubuntu-24.04",
        "provider_status": "active",
        "visibility": "shared",
        "is_protected": True,
        "container_format": "bare",
        "disk_format": "qcow2",
        "size_bytes": 2_147_483_648,
        "virtual_size_bytes": 10_737_418_240,
        "tags": ["cmp-catalog-approved", "ubuntu"],
        "properties": {"os_distro": "ubuntu"},
        "checksum": "a" * 32,
        "min_disk_gib": 20,
        "min_ram_mib": 2048,
        "catalog_approved": True,
    }

    payload = InventoryBatchPayload.model_validate(
        _payload(
            resource_type="image",
            items=[item],
            item_count=1,
            checksum=compute_inventory_checksum([item]),
        )
    )

    assert payload.items[0].visibility == "shared"
    assert payload.items[0].size_bytes == 2_147_483_648
    assert payload.items[0].catalog_approved is True


def test_flavor_batch_accepts_enriched_catalog_detail_fields() -> None:
    item = {
        "provider_resource_id": "flavor-1",
        "name": "compute.medium",
        "provider_status": "active",
        "vcpus": 4,
        "ram_mib": 8192,
        "root_disk_gib": 80,
        "ephemeral_disk_gib": 20,
        "swap_mib": 1024,
        "is_public": False,
        "enabled": True,
        "extra_specs": {"hw:cpu_policy": "dedicated"},
        "access_project_ids": ["project-1"],
        "catalog_approved": True,
    }

    payload = InventoryBatchPayload.model_validate(
        _payload(
            resource_type="flavor",
            items=[item],
            item_count=1,
            checksum=compute_inventory_checksum([item]),
        )
    )

    assert payload.items[0].vcpus == 4
    assert payload.items[0].access_project_ids == ["project-1"]


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("visibility", "internal", "visibility"),
        ("size_bytes", -1, "size_bytes"),
        ("disk_format", "QCOW2", "disk_format"),
        ("properties", {"password": "synthetic-secret"}, "properties"),
    ],
)
def test_image_batch_rejects_invalid_or_secret_catalog_detail(
    field: str, value: object, match: str
) -> None:
    item = {
        "provider_resource_id": "image-invalid",
        "name": "invalid",
        "provider_status": "active",
        "visibility": "private",
        "disk_format": "qcow2",
        field: value,
    }
    with pytest.raises(ValidationError, match=match):
        InventoryBatchPayload.model_validate(
            _payload(
                resource_type="image",
                items=[item],
                item_count=1,
                checksum=compute_inventory_checksum([item]),
            )
        )


@pytest.mark.parametrize("fixture_path", CATALOG_FIXTURE_PATHS, ids=lambda path: path.stem)
def test_catalog_inventory_fixtures_validate_against_canonical_schema(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload = fixture["payload"]
    assert isinstance(payload, dict)
    InventoryBatchPayload.model_validate(payload)

    schema = json.loads(INVENTORY_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)

    assert fixture["schema_version"] == "1.1"


def test_inventory_json_schema_preserves_existing_volume_fields() -> None:
    item = {
        "provider_resource_id": "volume-1",
        "name": "data",
        "provider_created_at": "2026-08-03T00:00:00Z",
        "provider_updated_at": "2026-08-03T01:00:00Z",
        "volume_type_provider_resource_id": "fast-1",
        "size_gib": 20,
        "bootable": False,
        "root": False,
        "encrypted": True,
        "metadata": {"tier": "gold"},
        "availability_zone": "nova",
        "attachments": [{"server_id": "server-1"}],
        "volume_provider_resource_id": "source-1",
        "snapshot_size_gib": 20,
    }
    payload = _payload(
        resource_type="volume",
        items=[item],
        item_count=1,
        checksum=compute_inventory_checksum([item]),
    )
    InventoryBatchPayload.model_validate(payload)

    schema = json.loads(INVENTORY_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
