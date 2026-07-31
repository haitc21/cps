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


@pytest.mark.parametrize(
    "parameters",
    [
        {"cidr": "10.0.0.0/24", "gateway_ip": "10.0.1.1"},
        {
            "cidr": "10.0.0.0/24",
            "allocation_pools": [{"start": "10.0.1.10", "end": "10.0.1.20"}],
        },
    ],
)
def test_subnet_rejects_gateway_or_pool_outside_cidr(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="inside subnet cidr"):
        _request(
            resource_type=NetworkResourceType.SUBNET,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            network_provider_resource_id="network-1",
            port_provider_resource_id=None,
            parameters=parameters,
        )


def test_external_network_mutation_is_admin_only() -> None:
    with pytest.raises(ValueError, match="administrator-only"):
        _request(
            resource_type=NetworkResourceType.NETWORK,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            port_provider_resource_id=None,
            parameters={"name": "provider", "router:external": True},
        )


def test_public_ingress_and_invalid_port_range_are_rejected() -> None:
    base = {
        "security_group_id": "sg-1",
        "direction": "ingress",
        "remote_ip_prefix": "0.0.0.0/0",
    }
    with pytest.raises(ValueError, match="public ingress"):
        _request(
            resource_type=NetworkResourceType.SECURITY_GROUP_RULE,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            port_provider_resource_id=None,
            parameters=base,
        )


def test_noncanonical_public_ingress_and_invalid_remote_prefix_are_rejected() -> None:
    base = {
        "security_group_id": "sg-1",
        "direction": "ingress",
    }
    with pytest.raises(ValueError, match="public ingress"):
        _request(
            resource_type=NetworkResourceType.SECURITY_GROUP_RULE,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            port_provider_resource_id=None,
            parameters=base | {"remote_ip_prefix": "0.0.0.1/0"},
        )
    with pytest.raises(ValueError, match="valid network"):
        _request(
            resource_type=NetworkResourceType.SECURITY_GROUP_RULE,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            port_provider_resource_id=None,
            parameters=base | {"remote_ip_prefix": "not-a-cidr"},
        )
    with pytest.raises(ValueError, match="invalid port range"):
        _request(
            resource_type=NetworkResourceType.SECURITY_GROUP_RULE,
            operation=NetworkOperation.CREATE,
            provider_resource_id=None,
            port_provider_resource_id=None,
            parameters=base
            | {"remote_ip_prefix": "10.0.0.0/8", "port_range_min": 443, "port_range_max": 22},
        )
