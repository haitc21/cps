"""Administrator-curated and member catalog schemas."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.safe_metadata import (
    is_secret_value,
    validate_bounded_string_list,
    validate_disk_format,
    validate_metadata_tree,
    validate_safe_catalog_string,
)

_CATALOG_STRING_MAX = 255
_CHECKSUM_MAX = 128
_PROVIDER_STATUS_MAX = 64
_DISK_FORMAT_MAX = 32
_MAX_COMPATIBILITY_PROJECT_IDS = 256

_MAX_RESPONSE_SERIALIZED_BYTES = 64 * 1024
_MAX_RESPONSE_LIST_ITEMS = 200

_IMAGE_SIZE_BYTES_MAX = 9_223_372_036_854_775_807
_VCPUS_MAX = 4096
_RAM_MIB_MAX = 16_777_216
_DISK_GIB_MAX = 1_048_576


def _bounded_optional_int(
    value: object,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} is out of range")
    return value


def _bounded_optional_bool(value: object, *, label: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError(f"{label} must be boolean")
    return value


class CatalogStoryResourceType(StrEnum):
    IMAGE = "image"
    FLAVOR = "flavor"


class CatalogResourceType(StrEnum):
    """Administrator catalog resource types including CPS-1703 curated inventory."""

    IMAGE = "image"
    FLAVOR = "flavor"
    NETWORK = "network"
    VOLUME_TYPE = "volume-type"
    AVAILABILITY_ZONE = "availability-zone"


class ImageVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"
    COMMUNITY = "community"


class CatalogImageSummary(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    provider_resource_id: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    name: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    provider_status: str | None = Field(default=None, max_length=_PROVIDER_STATUS_MAX)
    lifecycle_state: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    project_provider_resource_id: str | None = Field(default=None, max_length=_CATALOG_STRING_MAX)
    visibility: str | None = Field(default=None, max_length=_CATALOG_STRING_MAX)
    size_bytes: int | None
    min_disk_gib: int | None
    min_ram_mib: int | None
    disk_format: str | None = Field(default=None, max_length=_DISK_FORMAT_MAX)
    checksum: str | None = Field(default=None, max_length=_CHECKSUM_MAX)
    catalog_approved: bool
    updated_at: datetime


class CatalogImageDetail(CatalogImageSummary):
    is_protected: bool | None = None
    container_format: str | None = Field(default=None, max_length=_CATALOG_STRING_MAX)
    virtual_size_bytes: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    member_project_ids: list[str] = Field(default_factory=list, max_length=256)
    provider_created_at: datetime | None = None
    provider_updated_at: datetime | None = None


class CatalogFlavorSummary(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    provider_resource_id: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    name: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    provider_status: str | None = Field(default=None, max_length=_PROVIDER_STATUS_MAX)
    lifecycle_state: str = Field(min_length=1, max_length=_CATALOG_STRING_MAX)
    vcpus: int | None
    ram_mib: int | None
    root_disk_gib: int | None
    ephemeral_disk_gib: int | None
    swap_mib: int | None
    is_public: bool | None
    enabled: bool | None
    catalog_approved: bool
    updated_at: datetime


class CatalogFlavorDetail(CatalogFlavorSummary):
    extra_specs: dict[str, Any] = Field(default_factory=dict)
    access_project_ids: list[str] = Field(default_factory=list, max_length=256)
    provider_created_at: datetime | None = None
    provider_updated_at: datetime | None = None


class CatalogCompatibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use: Literal["LAUNCH", "REBUILD", "RESIZE", "VOLUME_FROM_IMAGE"]
    provider_connection_id: uuid.UUID
    image_provider_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    flavor_provider_resource_id: str | None = Field(default=None, min_length=1, max_length=255)


class CatalogCompatibilityResult(BaseModel):
    compatible: bool
    reason_codes: list[str]


def catalog_approved_from_attributes(attributes: dict[str, Any]) -> bool:
    value = attributes.get("catalog_approved")
    return value is True


def _provider_attributes(row: Any) -> dict[str, Any]:
    attributes = getattr(row, "provider_attributes", None)
    if attributes is None:
        return {}
    if not isinstance(attributes, dict):
        raise ValueError("provider_attributes is invalid")
    return attributes


def _required_catalog_string(
    value: object,
    *,
    label: str,
    max_length: int = _CATALOG_STRING_MAX,
) -> str:
    return validate_safe_catalog_string(value, label=label, max_length=max_length)


def _optional_catalog_string(
    value: object,
    *,
    label: str,
    max_length: int = _CATALOG_STRING_MAX,
) -> str | None:
    if value is None:
        return None
    return validate_safe_catalog_string(value, label=label, max_length=max_length)


def _optional_strict_non_negative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _optional_bounded_container_format(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise ValueError("container_format must be a non-empty string")
    if len(value) > 255:
        raise ValueError("container_format exceeds maximum length")
    if is_secret_value(value):
        raise ValueError("forbidden secret-bearing metadata value")
    return value


def _enforce_catalog_response_bounds(model: BaseModel) -> None:
    serialized = json.dumps(
        model.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(serialized) > _MAX_RESPONSE_SERIALIZED_BYTES:
        raise ValueError("catalog response exceeds maximum serialized size")


def enforce_catalog_response_list_bounds(items: list[BaseModel]) -> None:
    if len(items) > _MAX_RESPONSE_LIST_ITEMS:
        raise ValueError("catalog response list exceeds maximum item count")
    for item in items:
        _enforce_catalog_response_bounds(item)


def _bounded_metadata_map(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata map is invalid")
    copy = dict(value)
    validate_metadata_tree(copy)
    return copy


def _bounded_string_list(value: object, *, max_items: int) -> list[str]:
    return validate_bounded_string_list(value, max_items=max_items)


def image_is_live(row: Any) -> bool:
    lifecycle = getattr(row, "lifecycle_state", None)
    status = getattr(row, "provider_status", None)
    return lifecycle == "ACTIVE" and isinstance(status, str) and status.lower() == "active"


def flavor_is_live(row: Any) -> bool:
    lifecycle = getattr(row, "lifecycle_state", None)
    enabled = getattr(row, "enabled", None)
    return lifecycle == "ACTIVE" and enabled is not False


def image_member_visible(row: Any) -> bool:
    visibility = getattr(row, "visibility", None)
    return image_is_live(row) and visibility in {"public", "community"}


def flavor_member_visible(row: Any) -> bool:
    is_public = getattr(row, "is_public", None)
    return flavor_is_live(row) and is_public is True


def image_visible_to_project(row: Any, project_provider_resource_id: str) -> bool:
    del project_provider_resource_id
    return image_member_visible(row)


def flavor_visible_to_project(row: Any, project_provider_resource_id: str) -> bool:
    del project_provider_resource_id
    return flavor_member_visible(row)


def _optional_bounded_disk_format(value: object) -> str | None:
    if value is None:
        return None
    try:
        return validate_disk_format(str(value))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def project_image_summary(row: Any) -> CatalogImageSummary:
    attributes = _provider_attributes(row)
    summary = CatalogImageSummary(
        id=row.id,
        provider_connection_id=row.provider_connection_id,
        provider_resource_id=_required_catalog_string(
            row.provider_resource_id,
            label="provider_resource_id",
        ),
        name=_required_catalog_string(row.name, label="name"),
        provider_status=_optional_catalog_string(
            row.provider_status,
            label="provider_status",
            max_length=_PROVIDER_STATUS_MAX,
        ),
        lifecycle_state=_required_catalog_string(row.lifecycle_state, label="lifecycle_state"),
        project_provider_resource_id=_optional_catalog_string(
            row.project_provider_resource_id,
            label="project_provider_resource_id",
        ),
        visibility=_optional_catalog_string(row.visibility, label="visibility"),
        size_bytes=_bounded_optional_int(
            row.size_bytes,
            minimum=0,
            maximum=_IMAGE_SIZE_BYTES_MAX,
            label="size_bytes",
        ),
        min_disk_gib=_bounded_optional_int(
            row.min_disk_gib,
            minimum=0,
            maximum=_DISK_GIB_MAX,
            label="min_disk_gib",
        ),
        min_ram_mib=_bounded_optional_int(
            row.min_ram_mib,
            minimum=0,
            maximum=_RAM_MIB_MAX,
            label="min_ram_mib",
        ),
        disk_format=_optional_bounded_disk_format(row.disk_format),
        checksum=_optional_catalog_string(row.checksum, label="checksum", max_length=_CHECKSUM_MAX),
        catalog_approved=catalog_approved_from_attributes(attributes),
        updated_at=row.updated_at,
    )
    _enforce_catalog_response_bounds(summary)
    return summary


def project_image_detail(row: Any) -> CatalogImageDetail:
    attributes = _provider_attributes(row)
    summary = project_image_summary(row)
    tags = attributes.get("tags")
    properties = attributes.get("properties")
    member_ids = attributes.get("member_project_ids")
    detail = CatalogImageDetail(
        **summary.model_dump(),
        is_protected=_bounded_optional_bool(attributes.get("is_protected"), label="is_protected"),
        container_format=_optional_bounded_container_format(attributes.get("container_format")),
        virtual_size_bytes=_optional_strict_non_negative_int(
            attributes.get("virtual_size_bytes"),
            "virtual_size_bytes",
        ),
        tags=_bounded_string_list(tags, max_items=64),
        properties=_bounded_metadata_map(properties),
        member_project_ids=_bounded_string_list(member_ids, max_items=256),
        provider_created_at=row.provider_created_at,
        provider_updated_at=row.provider_updated_at,
    )
    _enforce_catalog_response_bounds(detail)
    return detail


def project_flavor_summary(row: Any) -> CatalogFlavorSummary:
    attributes = _provider_attributes(row)
    summary = CatalogFlavorSummary(
        id=row.id,
        provider_connection_id=row.provider_connection_id,
        provider_resource_id=_required_catalog_string(
            row.provider_resource_id,
            label="provider_resource_id",
        ),
        name=_required_catalog_string(row.name, label="name"),
        provider_status=_optional_catalog_string(
            row.provider_status,
            label="provider_status",
            max_length=_PROVIDER_STATUS_MAX,
        ),
        lifecycle_state=_required_catalog_string(row.lifecycle_state, label="lifecycle_state"),
        vcpus=_bounded_optional_int(row.vcpus, minimum=0, maximum=_VCPUS_MAX, label="vcpus"),
        ram_mib=_bounded_optional_int(
            row.ram_mib,
            minimum=0,
            maximum=_RAM_MIB_MAX,
            label="ram_mib",
        ),
        root_disk_gib=_bounded_optional_int(
            row.root_disk_gib,
            minimum=0,
            maximum=_DISK_GIB_MAX,
            label="root_disk_gib",
        ),
        ephemeral_disk_gib=_bounded_optional_int(
            row.ephemeral_disk_gib,
            minimum=0,
            maximum=_DISK_GIB_MAX,
            label="ephemeral_disk_gib",
        ),
        swap_mib=_bounded_optional_int(
            row.swap_mib,
            minimum=0,
            maximum=_RAM_MIB_MAX,
            label="swap_mib",
        ),
        is_public=_bounded_optional_bool(row.is_public, label="is_public"),
        enabled=_bounded_optional_bool(row.enabled, label="enabled"),
        catalog_approved=catalog_approved_from_attributes(attributes),
        updated_at=row.updated_at,
    )
    _enforce_catalog_response_bounds(summary)
    return summary


def project_flavor_detail(row: Any) -> CatalogFlavorDetail:
    attributes = _provider_attributes(row)
    summary = project_flavor_summary(row)
    extra_specs = attributes.get("extra_specs")
    access_ids = attributes.get("access_project_ids")
    detail = CatalogFlavorDetail(
        **summary.model_dump(),
        extra_specs=_bounded_metadata_map(extra_specs),
        access_project_ids=_bounded_string_list(access_ids, max_items=256),
        provider_created_at=row.provider_created_at,
        provider_updated_at=row.provider_updated_at,
    )
    _enforce_catalog_response_bounds(detail)
    return detail


def compatibility_image_snapshot_fields(
    attributes: dict[str, Any],
    *,
    min_disk_gib: int | None = None,
    min_ram_mib: int | None = None,
) -> tuple[str | None, list[str]]:
    """Project legacy image attributes consumed by compatibility; raises on invalid."""
    _bounded_optional_int(min_disk_gib, minimum=0, maximum=_DISK_GIB_MAX, label="min_disk_gib")
    _bounded_optional_int(min_ram_mib, minimum=0, maximum=_RAM_MIB_MAX, label="min_ram_mib")
    container_format = _optional_bounded_container_format(attributes.get("container_format"))
    member_ids = validate_bounded_string_list(
        attributes.get("member_project_ids"),
        max_items=256,
    )
    return container_format, member_ids


def compatibility_flavor_snapshot_fields(
    attributes: dict[str, Any],
    *,
    ram_mib: int | None = None,
    root_disk_gib: int | None = None,
) -> list[str]:
    """Project legacy flavor attributes consumed by compatibility; raises on invalid."""
    _bounded_optional_int(ram_mib, minimum=0, maximum=_RAM_MIB_MAX, label="ram_mib")
    _bounded_optional_int(
        root_disk_gib,
        minimum=0,
        maximum=_DISK_GIB_MAX,
        label="root_disk_gib",
    )
    return validate_bounded_string_list(attributes.get("access_project_ids"), max_items=256)
