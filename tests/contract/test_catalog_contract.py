from cps.api.schemas.catalog import CatalogResourceType


def test_catalog_contract_is_read_only_and_allowlisted() -> None:
    assert {item.value for item in CatalogResourceType} == {
        "image",
        "flavor",
        "network",
        "volume-type",
        "availability-zone",
    }
