"""CPS-302 inventory batch contract tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from cps.contracts.messages.inventory import (
    InventoryBatchPayload,
    InventoryResourceType,
    compute_inventory_checksum,
)


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
