"""CPS-1704 fail-closed network policy tests."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import (
    CatalogPolicyViolationError,
    NetworkPolicyViolationError,
    NetworkQuotaExceededError,
    ProviderConnectionNotFoundError,
)
from cps.contracts.messages.network_operations import (
    NetworkOperation,
    NetworkOperationRequest,
    NetworkResourceType,
)


def _request(resource_type: NetworkResourceType, **overrides: object) -> NetworkOperationRequest:
    payload = {
        "operation_id": uuid.uuid4(),
        "resource_type": resource_type,
        "operation": NetworkOperation.CREATE,
        "provider_connection_id": uuid.uuid4(),
        "project_provider_resource_id": "project-1",
        "parameters": {},
    }
    payload.update(overrides)
    return NetworkOperationRequest.model_validate(payload)


def _service(inventory: SimpleNamespace) -> OperationApplicationService:
    return OperationApplicationService(SimpleNamespace(), SimpleNamespace(), inventory)


def test_subnet_overlap_fails_before_publish() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        list_resources=AsyncMock(
            side_effect=[
                ([SimpleNamespace(project_provider_resource_id="project-1")], 1),
                (
                    [
                        SimpleNamespace(
                            provider_attributes={"cidr": "10.0.0.0/24"},
                        )
                    ],
                    1,
                ),
            ]
        ),
    )
    request = _request(
        NetworkResourceType.SUBNET,
        network_provider_resource_id="network-1",
        parameters={"cidr": "10.0.0.128/25"},
    )
    with pytest.raises(NetworkPolicyViolationError):
        asyncio.run(
            _service(inventory)._validate_network_operation_policy(
                request.provider_connection_id, request
            )
        )


def test_subnet_overlap_comparison_allows_different_ip_families() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        list_resources=AsyncMock(
            side_effect=[
                ([SimpleNamespace(project_provider_resource_id="project-1")], 1),
                ([SimpleNamespace(provider_attributes={"cidr": "2001:db8::/64"})], 1),
                ([], 0),
            ]
        ),
    )
    request = _request(
        NetworkResourceType.SUBNET,
        network_provider_resource_id="network-1",
        parameters={"cidr": "10.0.0.0/24"},
    )

    asyncio.run(
        _service(inventory)._validate_network_operation_policy(
            request.provider_connection_id, request
        )
    )


def test_foreign_relationship_reference_fails_closed() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=False),
    )
    request = _request(
        NetworkResourceType.PORT,
        network_provider_resource_id="foreign-network",
    )
    with pytest.raises(ProviderConnectionNotFoundError):
        asyncio.run(
            _service(inventory)._validate_network_operation_policy(
                request.provider_connection_id, request
            )
        )


def test_same_connection_but_foreign_project_reference_fails_closed() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        list_resources=AsyncMock(
            return_value=(
                [SimpleNamespace(project_provider_resource_id="project-2")],
                1,
            )
        ),
    )
    request = _request(
        NetworkResourceType.PORT,
        network_provider_resource_id="foreign-network",
    )
    with pytest.raises(ProviderConnectionNotFoundError):
        asyncio.run(
            _service(inventory)._validate_network_operation_policy(
                request.provider_connection_id, request
            )
        )


def test_unapproved_external_network_fails_closed() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        catalog_resource_is_approved=AsyncMock(return_value=False),
    )
    request = _request(
        NetworkResourceType.FLOATING_IP,
        operation=NetworkOperation.ALLOCATE,
        network_provider_resource_id="external-network-1",
    )
    with pytest.raises(CatalogPolicyViolationError):
        asyncio.run(
            _service(inventory)._validate_network_operation_policy(
                request.provider_connection_id, request
            )
        )


def test_exhausted_network_quota_fails_before_publish() -> None:
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        list_resources=AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        service="network",
                        resource_name="networks",
                        unlimited=False,
                        limit_value=2,
                        in_use=2,
                    )
                ],
                1,
            )
        ),
    )
    request = _request(NetworkResourceType.NETWORK, parameters={"name": "third"})
    with pytest.raises(NetworkQuotaExceededError):
        asyncio.run(
            _service(inventory)._validate_network_operation_policy(
                request.provider_connection_id, request
            )
        )
