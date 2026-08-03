"""Canonical safe image command contract."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from cps.contracts.messages.image_operations import ImageOperationRequest


def test_image_import_contract_is_https_only_and_has_no_request_allowlist() -> None:
    command = ImageOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation="import_url",
        name="cmp-image",
        disk_format="qcow2",
        source_url="https://images.example.test/cmp.qcow2",
    )
    assert command.resource_type == "image"
    with pytest.raises(ValidationError):
        ImageOperationRequest(
            operation_id=uuid4(),
            provider_connection_id=uuid4(),
            operation="import_url",
            name="cmp-image",
            disk_format="qcow2",
            source_url="https://evil.example/cmp.qcow2",
        )
