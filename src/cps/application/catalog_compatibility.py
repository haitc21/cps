"""Provider-neutral catalog compatibility evaluation."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cps.contracts.safe_metadata import validate_disk_format, validate_safe_project_id

_VCPUS_MAX = 4096
_RAM_MIB_MAX = 16_777_216
_DISK_GIB_MAX = 1_048_576


class CatalogUse(StrEnum):
    LAUNCH = "LAUNCH"
    REBUILD = "REBUILD"
    RESIZE = "RESIZE"
    VOLUME_FROM_IMAGE = "VOLUME_FROM_IMAGE"


class CompatibilityReason(StrEnum):
    IMAGE_NOT_FOUND = "IMAGE_NOT_FOUND"
    FLAVOR_NOT_FOUND = "FLAVOR_NOT_FOUND"
    IMAGE_NOT_APPROVED = "IMAGE_NOT_APPROVED"
    FLAVOR_NOT_APPROVED = "FLAVOR_NOT_APPROVED"
    IMAGE_NOT_LIVE = "IMAGE_NOT_LIVE"
    FLAVOR_NOT_LIVE = "FLAVOR_NOT_LIVE"
    IMAGE_FORMAT_NOT_LAUNCHABLE = "IMAGE_FORMAT_NOT_LAUNCHABLE"
    IMAGE_SCOPE_MISMATCH = "IMAGE_SCOPE_MISMATCH"
    FLAVOR_SCOPE_MISMATCH = "FLAVOR_SCOPE_MISMATCH"
    CATALOG_DATA_INCOMPLETE = "CATALOG_DATA_INCOMPLETE"
    FLAVOR_RAM_BELOW_IMAGE_MINIMUM = "FLAVOR_RAM_BELOW_IMAGE_MINIMUM"
    FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM = "FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM"


class CatalogImageSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    provider_connection_id: uuid.UUID
    provider_resource_id: str = Field(min_length=1, max_length=255)
    lifecycle_state: str = Field(min_length=1, max_length=255)
    provider_status: str | None = Field(default=None, max_length=64)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    visibility: str | None = Field(default=None, max_length=255)
    disk_format: str | None = Field(default=None, max_length=32)
    container_format: str | None = Field(default=None, max_length=255)
    min_disk_gib: int | None = Field(default=None, ge=0, le=_DISK_GIB_MAX)
    min_ram_mib: int | None = Field(default=None, ge=0, le=_RAM_MIB_MAX)
    catalog_approved: bool = False
    member_project_ids: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("member_project_ids", mode="before")
    @classmethod
    def validate_member_project_ids(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("member_project_ids must be a list")
        return [validate_safe_project_id(item, label="member_project_ids entry") for item in value]


class CatalogFlavorSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    provider_connection_id: uuid.UUID
    provider_resource_id: str = Field(min_length=1, max_length=255)
    lifecycle_state: str = Field(min_length=1, max_length=255)
    enabled: bool | None = None
    is_public: bool | None = None
    ram_mib: int | None = Field(default=None, ge=0, le=_RAM_MIB_MAX)
    root_disk_gib: int | None = Field(default=None, ge=0, le=_DISK_GIB_MAX)
    catalog_approved: bool = False
    access_project_ids: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("access_project_ids", mode="before")
    @classmethod
    def validate_access_project_ids(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("access_project_ids must be a list")
        return [validate_safe_project_id(item, label="access_project_ids entry") for item in value]


class CatalogCompatibilityResult(NamedTuple):
    compatible: bool
    reason_codes: list[CompatibilityReason]


_NON_LAUNCHABLE_DISK_FORMATS = frozenset({"aki", "ari"})
_NON_LAUNCHABLE_CONTAINER_FORMATS = frozenset({"docker"})


def evaluate_catalog_compatibility(
    *,
    use: CatalogUse,
    image: CatalogImageSnapshot | None,
    flavor: CatalogFlavorSnapshot | None,
    provider_connection_id: uuid.UUID,
    project_provider_resource_id: str,
) -> CatalogCompatibilityResult:
    reasons: list[CompatibilityReason] = []
    needs_flavor = use in {CatalogUse.LAUNCH, CatalogUse.REBUILD, CatalogUse.RESIZE}

    if image is None:
        reasons.append(CompatibilityReason.IMAGE_NOT_FOUND)
    if needs_flavor and flavor is None:
        reasons.append(CompatibilityReason.FLAVOR_NOT_FOUND)

    if image is not None:
        if image.provider_connection_id != provider_connection_id:
            reasons.append(CompatibilityReason.IMAGE_SCOPE_MISMATCH)
        if not image.catalog_approved:
            reasons.append(CompatibilityReason.IMAGE_NOT_APPROVED)
        if image.lifecycle_state != "ACTIVE" or (
            image.provider_status or ""
        ).lower() != "active":
            reasons.append(CompatibilityReason.IMAGE_NOT_LIVE)
        if not _image_scope_allows(image, project_provider_resource_id):
            reasons.append(CompatibilityReason.IMAGE_SCOPE_MISMATCH)
        if not _image_is_launchable(image):
            reasons.append(CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE)
        if use == CatalogUse.VOLUME_FROM_IMAGE and not _image_has_volume_dimensions(image):
            reasons.append(CompatibilityReason.CATALOG_DATA_INCOMPLETE)
        if needs_flavor and not _image_has_launch_dimensions(image):
            reasons.append(CompatibilityReason.CATALOG_DATA_INCOMPLETE)

    if needs_flavor and flavor is not None:
        if flavor.provider_connection_id != provider_connection_id:
            reasons.append(CompatibilityReason.FLAVOR_SCOPE_MISMATCH)
        if not flavor.catalog_approved:
            reasons.append(CompatibilityReason.FLAVOR_NOT_APPROVED)
        if flavor.lifecycle_state != "ACTIVE" or flavor.enabled is False:
            reasons.append(CompatibilityReason.FLAVOR_NOT_LIVE)
        if not _flavor_scope_allows(flavor, project_provider_resource_id):
            reasons.append(CompatibilityReason.FLAVOR_SCOPE_MISMATCH)
        if not _flavor_dimensions_valid(flavor):
            reasons.append(CompatibilityReason.CATALOG_DATA_INCOMPLETE)

    if image is not None and needs_flavor and flavor is not None:
        if image.min_ram_mib is not None and (
            flavor.ram_mib is None or flavor.ram_mib < image.min_ram_mib
        ):
            reasons.append(CompatibilityReason.FLAVOR_RAM_BELOW_IMAGE_MINIMUM)
        if image.min_disk_gib is not None and (
            flavor.root_disk_gib is None or flavor.root_disk_gib < image.min_disk_gib
        ):
            reasons.append(CompatibilityReason.FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM)
        if flavor.ram_mib is None or flavor.root_disk_gib is None:
            reasons.append(CompatibilityReason.CATALOG_DATA_INCOMPLETE)

    ordered = _dedupe_ordered(reasons)
    return CatalogCompatibilityResult(compatible=not ordered, reason_codes=ordered)


def _dedupe_ordered(reasons: list[CompatibilityReason]) -> list[CompatibilityReason]:
    seen: set[CompatibilityReason] = set()
    ordered: list[CompatibilityReason] = []
    for reason in CompatibilityReason:
        if reason in reasons and reason not in seen:
            seen.add(reason)
            ordered.append(reason)
    return ordered


def _image_scope_allows(image: CatalogImageSnapshot, project_id: str) -> bool:
    del project_id
    return image.visibility in {"public", "community"}


def _flavor_scope_allows(flavor: CatalogFlavorSnapshot, project_id: str) -> bool:
    del project_id
    return flavor.is_public is True


def _flavor_dimensions_valid(flavor: CatalogFlavorSnapshot) -> bool:
    del flavor
    return True


def _disk_format_is_valid(disk_format: str | None) -> bool:
    if disk_format is None:
        return False
    try:
        validate_disk_format(disk_format)
    except ValueError:
        return False
    return True


def _image_is_launchable(image: CatalogImageSnapshot) -> bool:
    if not _disk_format_is_valid(image.disk_format):
        return False
    disk = image.disk_format or ""
    container = (image.container_format or "").lower()
    if not container:
        return False
    if disk in _NON_LAUNCHABLE_DISK_FORMATS:
        return False
    return container not in _NON_LAUNCHABLE_CONTAINER_FORMATS


def _image_has_volume_dimensions(image: CatalogImageSnapshot) -> bool:
    if image.min_disk_gib is None:
        return False
    disk = image.disk_format or ""
    container = (image.container_format or "").lower()
    return bool(_disk_format_is_valid(disk) and container)


def _image_has_launch_dimensions(image: CatalogImageSnapshot) -> bool:
    return image.min_disk_gib is not None and image.min_ram_mib is not None
