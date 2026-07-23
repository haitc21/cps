"""Safe inventory API projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InventoryResourceView(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    provider_resource_id: str
    name: str
    description: str | None
    provider_status: str | None
    lifecycle_state: str
    provider_created_at: datetime | None
    provider_updated_at: datetime | None
    last_seen_at: datetime | None
    deleted_at: datetime | None
    last_sync_id: uuid.UUID | None
    provider_attributes: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class InventoryPage(BaseModel):
    items: list[InventoryResourceView]
    page: dict[str, int]


class InventorySyncRequest(BaseModel):
    collections: list[str] = Field(
        default_factory=lambda: [
            "region",
            "project",
            "flavor",
            "image",
            "network",
            "subnet",
            "port",
            "volume",
            "instance",
        ],
        min_length=1,
    )
    batch_size: int = Field(default=100, ge=1, le=1000)


class InventoryRefreshRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=32)
    provider_resource_id: str = Field(min_length=1, max_length=255)
