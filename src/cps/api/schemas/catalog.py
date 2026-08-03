"""Administrator-curated, read-only resource catalog schemas."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel

from cps.api.schemas.inventory import InventoryResourceView


class CatalogResourceType(StrEnum):
    IMAGE = "image"
    FLAVOR = "flavor"
    NETWORK = "network"
    VOLUME_TYPE = "volume-type"
    AVAILABILITY_ZONE = "availability-zone"


class CatalogMemberResourceType(StrEnum):
    IMAGE = "image"
    FLAVOR = "flavor"


class CatalogImageSummary(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    provider_resource_id: str
    name: str
    provider_status: str | None
    visibility: str | None
    size_bytes: int | None
    min_disk_gib: int | None
    min_ram_mib: int | None
    disk_format: str | None
    checksum: str | None
    catalog_approved: bool


class CatalogFlavorSummary(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    provider_resource_id: str
    name: str
    provider_status: str | None
    vcpus: int | None
    ram_mib: int | None
    root_disk_gib: int | None
    ephemeral_disk_gib: int | None
    swap_mib: int | None
    is_public: bool | None
    enabled: bool | None
    catalog_approved: bool


CatalogMemberResourceSummary = CatalogImageSummary | CatalogFlavorSummary


class CatalogPage(BaseModel):
    items: list[InventoryResourceView]
    page: dict[str, int]
