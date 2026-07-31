"""CPS-1703 catalog reference enforcement tests."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import CatalogPolicyViolationError
from cps.contracts.messages.instance import InstanceBootSource, InstanceCreateRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_operations import VolumeOperation, VolumeOperationRequest


def _service(
    *, approved: bool
) -> tuple[OperationApplicationService, SimpleNamespace, SimpleNamespace]:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
    repository = SimpleNamespace(get_provider_connection=AsyncMock(return_value=connection))
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        resource_name_belongs_to_connection=AsyncMock(return_value=True),
        catalog_resource_is_approved=AsyncMock(return_value=approved),
    )
    return (
        OperationApplicationService(repository, SimpleNamespace(), inventory),
        inventory,
        connection,
    )


def test_instance_create_rejects_unapproved_availability_zone_before_publish() -> None:
    service, inventory, connection = _service(approved=True)
    inventory.catalog_resource_is_approved.side_effect = [True, True, False]
    request = InstanceCreateRequest(
        name="demo",
        flavor_provider_resource_id="flavor-1",
        boot_source=InstanceBootSource.IMAGE,
        image_provider_resource_id="image-1",
        network_provider_resource_ids=["network-1"],
        availability_zone="az-private",
    )

    with pytest.raises(CatalogPolicyViolationError):
        asyncio.run(
            service.create_instance(
                connection.id,
                idempotency_key="instance-unapproved-az",
                correlation_id=uuid.uuid4(),
                request=request,
            )
        )


@pytest.mark.parametrize(
    ("volume_type", "availability_zone"),
    [("type-private", None), (None, "az-private")],
)
def test_volume_create_rejects_unapproved_catalog_reference_before_publish(
    volume_type: str | None,
    availability_zone: str | None,
) -> None:
    service, _inventory, connection = _service(approved=False)
    request = VolumeOperationRequest(
        operation_id=uuid.uuid4(),
        operation=VolumeOperation.CREATE,
        required_scope=ScopeKind.PROJECT,
        provider_connection_id=connection.id,
        name="data",
        size_gib=1,
        volume_type_provider_resource_id=volume_type,
        availability_zone=availability_zone,
    )

    with pytest.raises(CatalogPolicyViolationError):
        asyncio.run(
            service.create_volume_operation(
                connection.id,
                idempotency_key="volume-unapproved-catalog",
                correlation_id=uuid.uuid4(),
                request=request,
            )
        )
