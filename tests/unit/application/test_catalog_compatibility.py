"""Deterministic catalog compatibility evaluation tests."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from cps.application.catalog_compatibility import (
    CatalogFlavorSnapshot,
    CatalogImageSnapshot,
    CatalogUse,
    CompatibilityReason,
    evaluate_catalog_compatibility,
)

CONNECTION_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
PROJECT_ID = "project-1"


def _live_image(**overrides: object) -> CatalogImageSnapshot:
    base = {
        "provider_connection_id": CONNECTION_ID,
        "provider_resource_id": "img-1",
        "lifecycle_state": "ACTIVE",
        "provider_status": "active",
        "project_provider_resource_id": PROJECT_ID,
        "visibility": "public",
        "disk_format": "qcow2",
        "container_format": "bare",
        "min_disk_gib": 20,
        "min_ram_mib": 512,
        "catalog_approved": True,
    }
    base.update(overrides)
    return CatalogImageSnapshot.model_validate(base)


def test_snapshot_rejects_overlong_provider_resource_id() -> None:
    with pytest.raises(ValidationError, match="provider_resource_id"):
        CatalogImageSnapshot.model_validate(
            {
                "provider_connection_id": CONNECTION_ID,
                "provider_resource_id": "x" * 256,
                "lifecycle_state": "ACTIVE",
            }
        )


def test_snapshot_rejects_oversized_project_id_list() -> None:
    with pytest.raises(ValidationError, match="member_project_ids"):
        CatalogImageSnapshot.model_validate(
            {
                "provider_connection_id": CONNECTION_ID,
                "provider_resource_id": "img-1",
                "lifecycle_state": "ACTIVE",
                "member_project_ids": [f"project-{index}" for index in range(257)],
            }
        )


def test_snapshot_rejects_empty_project_id() -> None:
    with pytest.raises(ValidationError, match="project"):
        CatalogImageSnapshot.model_validate(
            {
                "provider_connection_id": CONNECTION_ID,
                "provider_resource_id": "img-1",
                "lifecycle_state": "ACTIVE",
                "member_project_ids": [""],
            }
        )


def test_snapshot_rejects_secret_bearing_project_id() -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        CatalogFlavorSnapshot.model_validate(
            {
                "provider_connection_id": CONNECTION_ID,
                "provider_resource_id": "flv-1",
                "lifecycle_state": "ACTIVE",
                "access_project_ids": ["password=project-secret"],
            }
        )


def _live_flavor(**overrides: object) -> CatalogFlavorSnapshot:
    base = {
        "provider_connection_id": CONNECTION_ID,
        "provider_resource_id": "flv-1",
        "lifecycle_state": "ACTIVE",
        "enabled": True,
        "is_public": True,
        "ram_mib": 2048,
        "root_disk_gib": 40,
        "catalog_approved": True,
    }
    base.update(overrides)
    return CatalogFlavorSnapshot.model_validate(base)


def test_launch_compatible_when_image_and_flavor_match() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert result.compatible is True
    assert result.reason_codes == []


@pytest.mark.parametrize(
    "use",
    [CatalogUse.LAUNCH, CatalogUse.REBUILD, CatalogUse.RESIZE],
)
def test_use_requires_flavor(use: CatalogUse) -> None:
    result = evaluate_catalog_compatibility(
        use=use,
        image=_live_image(),
        flavor=None,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_NOT_FOUND in result.reason_codes


def test_volume_from_image_skips_flavor_checks() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.VOLUME_FROM_IMAGE,
        image=_live_image(),
        flavor=None,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert result.compatible is True


def test_volume_from_image_rejects_non_launchable_formats() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.VOLUME_FROM_IMAGE,
        image=_live_image(disk_format="aki", container_format="bare"),
        flavor=None,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE in result.reason_codes


def test_volume_from_image_requires_complete_dimensions() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.VOLUME_FROM_IMAGE,
        image=_live_image(min_disk_gib=None),
        flavor=None,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.CATALOG_DATA_INCOMPLETE in result.reason_codes


@pytest.mark.parametrize(
    ("visibility", "member_ids", "compatible"),
    [
        ("public", [], True),
        ("community", [], True),
        ("shared", ["project-1"], False),
        ("private", [], False),
    ],
)
def test_image_scope_matrix(visibility: str, member_ids: list[str], compatible: bool) -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(visibility=visibility, member_project_ids=member_ids),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert result.compatible is compatible


def test_docker_container_is_not_launchable() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(container_format="docker"),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE in result.reason_codes


def test_stale_image_is_not_live() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(lifecycle_state="DELETED"),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_NOT_LIVE in result.reason_codes


def test_flavor_root_disk_below_image_minimum() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(min_disk_gib=80),
        flavor=_live_flavor(root_disk_gib=40),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_ROOT_DISK_BELOW_IMAGE_MINIMUM in result.reason_codes


def test_incomplete_flavor_dimensions_fail_closed() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(root_disk_gib=None),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.CATALOG_DATA_INCOMPLETE in result.reason_codes


def test_reason_codes_are_deterministic_and_ordered() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=None,
        flavor=None,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert result.reason_codes == [
        CompatibilityReason.IMAGE_NOT_FOUND,
        CompatibilityReason.FLAVOR_NOT_FOUND,
    ]


def test_private_image_is_not_member_scoped() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(visibility="private", project_provider_resource_id=PROJECT_ID),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_SCOPE_MISMATCH in result.reason_codes


@pytest.mark.parametrize("use", [CatalogUse.LAUNCH, CatalogUse.REBUILD, CatalogUse.RESIZE])
def test_launch_family_requires_image_min_disk_and_min_ram(use: CatalogUse) -> None:
    result = evaluate_catalog_compatibility(
        use=use,
        image=_live_image(min_disk_gib=None, min_ram_mib=None),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.CATALOG_DATA_INCOMPLETE in result.reason_codes


def test_private_image_requires_owner_project() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(visibility="private", project_provider_resource_id="other"),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_SCOPE_MISMATCH in result.reason_codes
    assert result.compatible is False


def test_aki_disk_format_is_not_launchable() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(disk_format="aki"),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_FORMAT_NOT_LAUNCHABLE in result.reason_codes


def test_flavor_ram_below_image_minimum() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(min_ram_mib=4096),
        flavor=_live_flavor(ram_mib=2048),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_RAM_BELOW_IMAGE_MINIMUM in result.reason_codes


@pytest.mark.parametrize("use", list(CatalogUse))
def test_compatible_launch_matrix_succeeds_for_all_uses(use: CatalogUse) -> None:
    flavor = _live_flavor() if use != CatalogUse.VOLUME_FROM_IMAGE else None
    result = evaluate_catalog_compatibility(
        use=use,
        image=_live_image(),
        flavor=flavor,
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert result.compatible is True
    assert result.reason_codes == []


def test_image_provider_connection_mismatch() -> None:
    other = uuid.UUID("99999999-9999-4999-8999-999999999999")
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(provider_connection_id=other),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_SCOPE_MISMATCH in result.reason_codes


def test_flavor_provider_connection_mismatch() -> None:
    other = uuid.UUID("99999999-9999-4999-8999-999999999999")
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(provider_connection_id=other),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_SCOPE_MISMATCH in result.reason_codes


def test_unapproved_flavor_is_rejected() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(catalog_approved=False),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_NOT_APPROVED in result.reason_codes


def test_stale_flavor_is_not_live() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(enabled=False),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_NOT_LIVE in result.reason_codes


def test_private_flavor_is_not_member_scoped() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(),
        flavor=_live_flavor(is_public=False, access_project_ids=[PROJECT_ID]),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.FLAVOR_SCOPE_MISMATCH in result.reason_codes


def test_unapproved_image_is_rejected() -> None:
    result = evaluate_catalog_compatibility(
        use=CatalogUse.LAUNCH,
        image=_live_image(catalog_approved=False),
        flavor=_live_flavor(),
        provider_connection_id=CONNECTION_ID,
        project_provider_resource_id=PROJECT_ID,
    )
    assert CompatibilityReason.IMAGE_NOT_APPROVED in result.reason_codes
