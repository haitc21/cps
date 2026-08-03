"""CPS-1904 instance snapshot wire-contract tests."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from cps.contracts.messages.instance_snapshot_operations import InstanceSnapshotRequest


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "operation_id": uuid.uuid4(),
        "provider_connection_id": uuid.uuid4(),
        "instance_provider_resource_id": "server-1",
        "project_provider_resource_id": "project-1",
        "name": "before-upgrade",
        "metadata": {"purpose": "recovery"},
    }
    value.update(overrides)
    return value


def test_instance_snapshot_contract_accepts_only_bounded_metadata() -> None:
    request = InstanceSnapshotRequest.model_validate(_request())

    assert request.name == "before-upgrade"
    assert request.metadata == {"purpose": "recovery"}
    assert "image_bytes" not in request.model_dump(mode="json")


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"metadata": {"pass" + "word": "not-allowed"}},
        {"metadata": {"purpose": "x" * 4097}},
        {"image_bytes": "not-a-contract-field"},
    ],
)
def test_instance_snapshot_contract_rejects_unsafe_or_binary_payload(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InstanceSnapshotRequest.model_validate(_request(**overrides))
