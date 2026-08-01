"""Safe inventory API projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from cps.api.schemas.catalog import catalog_approved_from_attributes


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
    domain_provider_resource_id: str | None = None
    domain_name: str | None = None
    owner_domain_provider_resource_id: str | None = None
    owner_project_provider_resource_id: str | None = None
    org_id: str | None = None
    workspace_id: str | None = None
    ownership_state: str | None = None
    enabled: bool | None = None
    principal_type: str | None = None
    principal_provider_resource_id: str | None = None
    role_provider_resource_id: str | None = None
    scope_kind: str | None = None
    scope_provider_resource_id: str | None = None
    inherited: bool | None = None
    service: str | None = None
    resource_name: str | None = None
    limit_value: int | None = None
    in_use: int | None = None
    unlimited: bool | None = None
    admin_state_up: bool | None = None
    shared: bool | None = None
    external: bool | None = None
    mtu: int | None = None
    network_provider_resource_id: str | None = None
    cidr: str | None = None
    ip_version: int | None = None
    gateway_ip: str | None = None
    enable_dhcp: bool | None = None
    external_gateway_info: dict[str, Any] | None = None
    routes: list[Any] | None = None
    stateful: bool | None = None
    security_group_provider_resource_id: str | None = None
    direction: str | None = None
    ethertype: str | None = None
    protocol: str | None = None
    port_range_min: int | None = None
    port_range_max: int | None = None
    remote_ip_prefix: str | None = None
    remote_group_provider_resource_id: str | None = None
    floating_network_provider_resource_id: str | None = None
    floating_ip: str | None = None
    fixed_ip: str | None = None
    port_provider_resource_id: str | None = None
    router_provider_resource_id: str | None = None
    status: str | None = None
    project_provider_resource_id: str | None = None
    volume_type_provider_resource_id: str | None = None
    size_gib: int | None = None
    bootable: bool | None = None
    root: bool | None = None
    encrypted: bool | None = None
    availability_zone: str | None = None
    metadata_values: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None
    volume_provider_resource_id: str | None = None
    snapshot_size_gib: int | None = None
    fingerprint: str | None = None
    key_type: str | None = None
    public_key: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class AdminCatalogCuratedView(InventoryResourceView):
    """CPS-1703 admin catalog projection without serializing raw provider_attributes."""

    catalog_approved: bool = False
    provider_attributes: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def derive_catalog_approved(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        attributes = value.get("provider_attributes")
        if isinstance(attributes, dict):
            data = dict(value)
            data["catalog_approved"] = catalog_approved_from_attributes(attributes)
            return data
        return value


def project_admin_catalog_curated_view(row: object) -> AdminCatalogCuratedView:
    """Project CPS-1703 admin catalog rows without raw provider_attributes."""
    if isinstance(row, dict):
        attributes = row.get("provider_attributes")
        curated = dict(row)
        if isinstance(attributes, dict):
            curated["catalog_approved"] = catalog_approved_from_attributes(attributes)
        return AdminCatalogCuratedView.model_validate(curated)
    attributes = getattr(row, "provider_attributes", None)
    curated_payload: dict[str, Any] = {}
    for name in AdminCatalogCuratedView.model_fields:
        if name in {"catalog_approved", "provider_attributes"}:
            continue
        if hasattr(row, name):
            curated_payload[name] = getattr(row, name)
    if isinstance(attributes, dict):
        curated_payload["catalog_approved"] = catalog_approved_from_attributes(attributes)
        curated_payload["provider_attributes"] = attributes
    return AdminCatalogCuratedView.model_validate(curated_payload)


class InventoryPage(BaseModel):
    items: list[InventoryResourceView]
    page: dict[str, int]


class InventorySyncRequest(BaseModel):
    collections: list[str] = Field(
        default_factory=lambda: [
            "domain",
            "region",
            "project",
            "flavor",
            "availability-zone",
            "image",
            "network",
            "subnet",
            "port",
            "router",
            "security-group",
            "security-group-rule",
            "floating-ip",
            "volume",
            "volume-type",
            "keypair",
            "instance",
            "role-assignment",
            "quota",
        ],
        min_length=1,
    )
    batch_size: int = Field(default=100, ge=1, le=1000)


class InventoryRefreshRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=32)
    provider_resource_id: str = Field(min_length=1, max_length=255)
