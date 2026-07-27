"""Administrator-curated, read-only resource catalog schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from cps.api.schemas.inventory import InventoryResourceView


class CatalogResourceType(StrEnum):
    IMAGE = "image"
    FLAVOR = "flavor"
    NETWORK = "network"
    VOLUME_TYPE = "volume-type"
    AVAILABILITY_ZONE = "availability-zone"


class CatalogPage(BaseModel):
    items: list[InventoryResourceView]
    page: dict[str, int]
