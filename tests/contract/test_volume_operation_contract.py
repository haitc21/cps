from uuid import uuid4

import pytest
from pydantic import ValidationError

from cps.contracts.messages.volume_operations import (
    VolumeAttachmentOperationRequest,
    VolumeOperationRequest,
)


def test_volume_lifecycle_contract_requires_create_fields_and_supports_resize():
    request = VolumeOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation="create",
        name="data-01",
        size_gib=10,
        project_provider_resource_id="project-1",
    )
    assert request.resource_type == "volume"
    assert request.size_gib == 10

    resized = request.model_copy(
        update={"operation": "resize", "provider_resource_id": "volume-1", "size_gib": 20}
    )
    assert resized.size_gib == 20


@pytest.mark.parametrize("operation", ["attach", "detach"])
def test_volume_attachment_contract_requires_both_provider_resources(operation):
    request = VolumeAttachmentOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation=operation,
        volume_provider_resource_id="volume-1",
        instance_provider_resource_id="instance-1",
        project_provider_resource_id="project-1",
    )
    assert request.resource_type == "volume-attachment"
    assert request.operation.value == operation


def test_volume_attachment_contract_rejects_missing_resource():
    with pytest.raises(ValidationError):
        VolumeAttachmentOperationRequest(
            operation_id=uuid4(),
            provider_connection_id=uuid4(),
            operation="attach",
            volume_provider_resource_id="volume-1",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "create", "size_gib": 10},
        {"operation": "resize", "provider_resource_id": "volume-1"},
        {"operation": "delete"},
    ],
)
def test_volume_lifecycle_contract_rejects_incomplete_payload(payload):
    with pytest.raises(ValidationError):
        VolumeOperationRequest(operation_id=uuid4(), provider_connection_id=uuid4(), **payload)
