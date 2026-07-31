"""CPS-1701 instance resize/rebuild policy tests."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.errors import InstanceStateConflictError
from cps.contracts.messages.instance import InstanceAction


@pytest.mark.parametrize(
    ("action", "provider_status"),
    [
        (InstanceAction.RESIZE, "PAUSED"),
        (InstanceAction.CONFIRM_RESIZE, "ACTIVE"),
        (InstanceAction.REVERT_RESIZE, "SHUTOFF"),
        (InstanceAction.REBUILD, "VERIFY_RESIZE"),
    ],
)
def test_advanced_instance_action_rejects_invalid_inventory_state_before_publish(
    action: InstanceAction,
    provider_status: str,
) -> None:
    connection_id = uuid.uuid4()
    repository = SimpleNamespace(
        get_provider_connection=AsyncMock(
            return_value=SimpleNamespace(id=connection_id, provider_id=uuid.uuid4())
        )
    )
    inventory = SimpleNamespace(
        resource_belongs_to_connection=AsyncMock(return_value=True),
        list_resources=AsyncMock(
            return_value=([SimpleNamespace(provider_status=provider_status)], 1)
        ),
    )
    outbox = SimpleNamespace()
    service = OperationApplicationService(repository, outbox, inventory)

    with pytest.raises(InstanceStateConflictError) as exc_info:
        asyncio.run(
            service.create_instance_action(
                connection_id,
                idempotency_key="instance-action-invalid-state",
                correlation_id=uuid.uuid4(),
                action=action,
                instance_provider_resource_id="server-1",
                resize_flavor_provider_resource_id=(
                    "flavor-2" if action is InstanceAction.RESIZE else None
                ),
                rebuild_image_provider_resource_id=(
                    "image-2" if action is InstanceAction.REBUILD else None
                ),
            )
        )

    assert exc_info.value.code == "INVALID_RESOURCE_STATE"
    inventory.list_resources.assert_awaited_once()
