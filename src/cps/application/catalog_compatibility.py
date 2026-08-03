"""Provider-neutral image/flavor compatibility policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


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


@dataclass(frozen=True)
class CatalogImageSnapshot:
    provider_connection_id: UUID
    catalog_approved: bool
    lifecycle_state: str
    provider_status: str | None
    visibility: str | None
    disk_format: str | None
    container_format: str | None
    min_disk_gib: int | None
    min_ram_mib: int | None
    owner_project_provider_resource_id: str | None = None
    member_project_ids: tuple[str, ...] | list[str] | None = None


@dataclass(frozen=True)
class CatalogFlavorSnapshot:
    provider_connection_id: UUID
    catalog_approved: bool
    lifecycle_state: str
    enabled: bool | None
    is_public: bool | None
    ram_mib: int | None
    root_disk_gib: int | None
    access_project_ids: tuple[str, ...] | list[str] | None = None


@dataclass(frozen=True)
class CatalogCompatibilityResult:
    compatible: bool
    reason_codes: list[CompatibilityReason]


def _image_is_live(image: CatalogImageSnapshot) -> bool:
    return image.lifecycle_state == "ACTIVE" and image.provider_status == "active"


def _flavor_is_live(flavor: CatalogFlavorSnapshot) -> bool:
    return flavor.lifecycle_state == "ACTIVE" and flavor.enabled is not False


def _image_scope_matches(image: CatalogImageSnapshot, project_id: str) -> bool:
    if image.visibility in {"public", "community"}:
        return True
    if image.visibility == "private":
        return image.owner_project_provider_resource_id == project_id
    if image.visibility == "shared":
        return image.member_project_ids is not None and project_id in image.member_project_ids
    return False


def _flavor_scope_matches(flavor: CatalogFlavorSnapshot, project_id: str) -> bool:
    return flavor.is_public is True or (
        flavor.access_project_ids is not None and project_id in flavor.access_project_ids
    )


def _image_format_is_launchable(image: CatalogImageSnapshot) -> bool:
    return (
        bool(image.disk_format)
        and bool(image.container_format)
        and image.disk_format not in {"aki", "ari"}
        and image.container_format != "docker"
    )


def evaluate_catalog_compatibility(
    *,
    use: CatalogUse,
    image: CatalogImageSnapshot | None,
    flavor: CatalogFlavorSnapshot | None,
    provider_connection_id: UUID,
    project_provider_resource_id: str,
) -> CatalogCompatibilityResult:
    """Evaluate persisted catalog snapshots without provider I/O."""
    requires_flavor = use is not CatalogUse.VOLUME_FROM_IMAGE
    reasons: set[CompatibilityReason] = set()

    if image is None:
        reasons.add(CompatibilityReason.IMAGE_NOT_FOUND)
    if requires_flavor and flavor is None:
        reasons.add(CompatibilityReason.FLAVOR_NOT_FOUND)

    if image is not None:
        if not image.catalog_approved:
            reasons.add(CompatibilityReason.IMAGE_NOT_APPROVED)
        if not _image_is_live(image):
            reasons.add(CompatibilityReason.IMAGE_NOT_LIVE)
        if not _image_format_is_launchable(image):
            reasons.add(CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE)
        if image.provider_connection_id != provider_connection_id or not _image_scope_matches(
            image, project_provider_resource_id
        ):
            reasons.add(CompatibilityReason.IMAGE_SCOPE_MISMATCH)
        if image.min_disk_gib is None or image.min_ram_mib is None:
            reasons.add(CompatibilityReason.CATALOG_DATA_INCOMPLETE)

    if requires_flavor and flavor is not None:
        if not flavor.catalog_approved:
            reasons.add(CompatibilityReason.FLAVOR_NOT_APPROVED)
        if not _flavor_is_live(flavor):
            reasons.add(CompatibilityReason.FLAVOR_NOT_LIVE)
        if flavor.provider_connection_id != provider_connection_id or not _flavor_scope_matches(
            flavor, project_provider_resource_id
        ):
            reasons.add(CompatibilityReason.FLAVOR_SCOPE_MISMATCH)
        if flavor.ram_mib is None or flavor.root_disk_gib is None:
            reasons.add(CompatibilityReason.CATALOG_DATA_INCOMPLETE)

    if image is not None and requires_flavor and flavor is not None:
        if image.min_ram_mib is not None and flavor.ram_mib is not None:
            if flavor.ram_mib < image.min_ram_mib:
                reasons.add(CompatibilityReason.FLAVOR_RAM_BELOW_IMAGE_MINIMUM)
        if image.min_disk_gib is not None and flavor.root_disk_gib is not None:
            if flavor.root_disk_gib < image.min_disk_gib:
                reasons.add(CompatibilityReason.FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM)

    ordered_reasons = [reason for reason in CompatibilityReason if reason in reasons]
    return CatalogCompatibilityResult(compatible=not ordered_reasons, reason_codes=ordered_reasons)
