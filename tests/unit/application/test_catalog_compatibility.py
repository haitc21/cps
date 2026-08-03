"""Pure catalog compatibility policy tests."""

from __future__ import annotations

import uuid

from cps.application.catalog_compatibility import (
    CatalogFlavorSnapshot,
    CatalogImageSnapshot,
    CatalogUse,
    CompatibilityReason,
    evaluate_catalog_compatibility,
)


def _image(connection_id: uuid.UUID, **overrides: object) -> CatalogImageSnapshot:
    values: dict[str, object] = {
        "provider_connection_id": connection_id,
        "catalog_approved": True,
        "lifecycle_state": "ACTIVE",
        "provider_status": "active",
        "visibility": "public",
        "disk_format": "qcow2",
        "container_format": "bare",
        "min_disk_gib": 20,
        "min_ram_mib": 2048,
    }
    values.update(overrides)
    return CatalogImageSnapshot(**values)


def _flavor(connection_id: uuid.UUID, **overrides: object) -> CatalogFlavorSnapshot:
    values: dict[str, object] = {
        "provider_connection_id": connection_id,
        "catalog_approved": True,
        "lifecycle_state": "ACTIVE",
        "enabled": True,
        "is_public": True,
        "ram_mib": 4096,
        "root_disk_gib": 40,
    }
    values.update(overrides)
    return CatalogFlavorSnapshot(**values)


def test_launch_compatibility_accepts_live_approved_public_resources() -> None:
    connection_id = uuid.uuid4()

    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_image(connection_id),
        flavor=_flavor(connection_id),
        provider_connection_id=connection_id,
        project_provider_resource_id="project-1",
    )

    assert result.compatible is True
    assert result.reason_codes == []


def test_launch_compatibility_reports_failures_in_declaration_order() -> None:
    connection_id = uuid.uuid4()

    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_image(
            uuid.uuid4(),
            catalog_approved=False,
            lifecycle_state="DELETED",
            provider_status="queued",
            disk_format="aki",
            visibility="private",
            owner_project_provider_resource_id="other-project",
            min_disk_gib=80,
            min_ram_mib=8192,
        ),
        flavor=_flavor(
            uuid.uuid4(),
            catalog_approved=False,
            lifecycle_state="DELETED",
            enabled=False,
            is_public=False,
            access_project_ids=[],
            ram_mib=1024,
            root_disk_gib=10,
        ),
        provider_connection_id=connection_id,
        project_provider_resource_id="project-1",
    )

    assert result.compatible is False
    assert result.reason_codes == [
        CompatibilityReason.IMAGE_NOT_APPROVED,
        CompatibilityReason.FLAVOR_NOT_APPROVED,
        CompatibilityReason.IMAGE_NOT_LIVE,
        CompatibilityReason.FLAVOR_NOT_LIVE,
        CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE,
        CompatibilityReason.IMAGE_SCOPE_MISMATCH,
        CompatibilityReason.FLAVOR_SCOPE_MISMATCH,
        CompatibilityReason.FLAVOR_RAM_BELOW_IMAGE_MINIMUM,
        CompatibilityReason.FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM,
    ]


def test_volume_from_image_does_not_require_a_flavor() -> None:
    connection_id = uuid.uuid4()

    result = evaluate_catalog_compatibility(
        use=CatalogUse.VOLUME_FROM_IMAGE,
        image=_image(connection_id),
        flavor=None,
        provider_connection_id=connection_id,
        project_provider_resource_id="project-1",
    )

    assert result.compatible is True
    assert result.reason_codes == []
