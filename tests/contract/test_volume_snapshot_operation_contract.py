from uuid import uuid4

import pytest
from pydantic import ValidationError

from cps.contracts.messages.volume_snapshot_operations import VolumeSnapshotOperationRequest


def test_snapshot_create_contract_requires_volume_and_name() -> None:
    request = VolumeSnapshotOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation="create",
        volume_provider_resource_id="volume-1",
        name="before-upgrade",
    )
    assert request.operation.value == "create"


@pytest.mark.parametrize("payload", [{"operation": "create"}, {"operation": "delete"}])
def test_snapshot_contract_rejects_incomplete_payload(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        VolumeSnapshotOperationRequest(
            operation_id=uuid4(), provider_connection_id=uuid4(), **payload
        )
