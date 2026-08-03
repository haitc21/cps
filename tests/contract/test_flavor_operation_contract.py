from uuid import uuid4

import pytest
from pydantic import ValidationError

from cps.contracts.messages.flavor_operations import FlavorOperationRequest


def test_flavor_contract_has_immutable_create_shape_and_explicit_mutations():
    created = FlavorOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation="create",
        provider_resource_id="auto",
        name="cmp-s19-small",
        vcpus=1,
        ram_mib=1024,
        disk_gib=10,
        is_public=False,
    )
    assert created.provider_resource_id is None
    assert created.required_scope == "SYSTEM"
    assert (
        FlavorOperationRequest(
            operation_id=uuid4(),
            provider_connection_id=uuid4(),
            operation="patch_extra_specs",
            provider_resource_id="flavor-1",
            extra_specs={"hw:cpu_policy": "shared"},
        ).resource_type
        == "flavor"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "create", "name": "bad", "vcpus": 1, "ram_mib": 1024},
        {"operation": "delete"},
        {
            "operation": "replace_access",
            "provider_resource_id": "f",
            "is_public": True,
            "access_project_ids": ["p"],
        },
    ],
)
def test_flavor_contract_rejects_incomplete_or_unsafe_mutations(payload):
    with pytest.raises(ValidationError):
        FlavorOperationRequest(operation_id=uuid4(), provider_connection_id=uuid4(), **payload)
