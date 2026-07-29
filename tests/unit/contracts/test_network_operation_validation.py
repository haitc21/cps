"""Contract validation for network topology commands."""

from __future__ import annotations

from uuid import uuid4

import pytest

from cps.contracts.messages.network_operations import (
    NetworkOperation,
    NetworkOperationRequest,
    NetworkResourceType,
)
from cps.contracts.messages.resource_operations import ScopeKind


def _request(**overrides: object) -> NetworkOperationRequest:
    payload = {
        "operation_id": uuid4(),
        "resource_type": NetworkResourceType.FLOATING_IP,
        "operation": NetworkOperation.ASSOCIATE,
        "required_scope": ScopeKind.PROJECT,
        "provider_connection_id": uuid4(),
        "provider_resource_id": "fip-1",
        "port_provider_resource_id": "port-1",
    }
    payload.update(overrides)
    return NetworkOperationRequest.model_validate(payload)


def test_floating_ip_associate_requires_port_reference() -> None:
    with pytest.raises(ValueError, match="port_provider_resource_id"):
        _request(port_provider_resource_id=None)


def test_floating_ip_associate_accepts_port_reference() -> None:
    request = _request()
    assert request.port_provider_resource_id == "port-1"


def test_floating_ip_allocate_requires_external_network() -> None:
    with pytest.raises(ValueError, match="external network"):
        NetworkOperationRequest.model_validate(
            {
                "operation_id": uuid4(),
                "resource_type": NetworkResourceType.FLOATING_IP,
                "operation": NetworkOperation.ALLOCATE,
                "required_scope": ScopeKind.PROJECT,
                "provider_connection_id": uuid4(),
            }
        )
