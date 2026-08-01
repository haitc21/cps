"""Inventory inbox ingress regressions for version-bound checksum validation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.inventory import (
    InventoryBatchItem,
    InventoryBatchPayload,
    compute_inventory_checksum_v1_0,
)
from cps.contracts.messages.types import INVENTORY_BATCH
from cps.domain.inventory.inbox_handler import InventoryEventError, InventoryInboxHandler


def _legacy_item() -> dict[str, object]:
    return {
        "provider_resource_id": "server-1",
        "name": "demo",
        "provider_status": "ACTIVE",
        "attributes": {"power_state": "RUNNING"},
    }


def _enriched_item() -> dict[str, object]:
    return {
        "provider_resource_id": "img-1",
        "name": "catalog",
        "provider_status": "active",
        "visibility": "public",
        "disk_format": "qcow2",
        "attributes": {"catalog_approved": True},
    }


def _batch_envelope(*, schema_version: str, payload: dict[str, object]) -> MessageEnvelope:
    return MessageEnvelope.model_validate(
        {
            "message_id": str(uuid.uuid4()),
            "message_type": INVENTORY_BATCH,
            "schema_version": schema_version,
            "occurred_at": "2026-08-01T00:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "operation_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
            "provider_connection_id": str(uuid.uuid4()),
            "payload": payload,
        }
    )


@pytest.mark.asyncio
async def test_inbox_rejects_schema_1_0_envelope_with_catalog_fields() -> None:
    item = _enriched_item()
    parsed_item = InventoryBatchItem.model_validate(item)
    envelope = _batch_envelope(
        schema_version="1.0",
        payload={
            "sync_id": str(uuid.uuid4()),
            "resource_type": "image",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": compute_inventory_checksum_v1_0([parsed_item]),
            "items": [item],
        },
    )
    handler = InventoryInboxHandler(AsyncMock(), AsyncMock())
    with pytest.raises(InventoryEventError, match="invalid"):
        await handler.handle(envelope)


def test_schema_1_0_envelope_accepts_only_v1_0_checksum_for_legacy_items() -> None:
    item = _legacy_item()
    parsed_item = InventoryBatchItem.model_validate(item)
    legacy_checksum = compute_inventory_checksum_v1_0([parsed_item])
    InventoryBatchPayload.model_validate(
        {
            "sync_id": str(uuid.uuid4()),
            "resource_type": "instance",
            "sequence": 1,
            "is_last": True,
            "collection_status": "COMPLETE",
            "item_count": 1,
            "checksum": legacy_checksum,
            "items": [item],
        },
        context={"schema_version": "1.0"},
    )
