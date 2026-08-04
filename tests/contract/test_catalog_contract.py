from cps.api.schemas.catalog import CatalogImageSummary, CatalogResourceType


def test_catalog_contract_is_read_only_and_allowlisted() -> None:
    assert {item.value for item in CatalogResourceType} == {
        "image",
        "flavor",
        "network",
        "volume-type",
        "availability-zone",
    }


def test_catalog_contract_has_additive_safe_presentation_fields() -> None:
    image = CatalogImageSummary.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "provider_connection_id": "00000000-0000-0000-0000-000000000002",
            "provider_resource_id": "image-1",
            "name": "ubuntu",
            "provider_status": "active",
            "visibility": "public",
            "size_bytes": 1,
            "min_disk_gib": 1,
            "min_ram_mib": 1,
            "disk_format": "qcow2",
            "checksum": "abc",
            "catalog_approved": True,
            "allowed_actions": ["deactivate"],
            "capabilities": {"deactivate": True},
        }
    )
    assert image.capabilities == {"deactivate": True}
    assert not hasattr(image, "user_data")
