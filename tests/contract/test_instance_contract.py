"""CPS-401 VM create contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cps.contracts.messages.instance import (
    InstanceAction,
    InstanceBootSource,
    InstanceCommandPayload,
    InstanceCreateRequest,
)


def _create(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "demo",
        "flavor_provider_resource_id": "flavor-1",
        "boot_source": "IMAGE",
        "image_provider_resource_id": "image-1",
        "network_provider_resource_ids": ["network-1"],
    }
    value.update(overrides)
    return value


def test_create_requires_explicit_network_or_port() -> None:
    with pytest.raises(ValidationError, match="explicit network or port"):
        InstanceCreateRequest.model_validate(_create(network_provider_resource_ids=[]))


def test_image_boot_rejects_root_volume_size() -> None:
    with pytest.raises(ValidationError, match="only valid"):
        InstanceCreateRequest.model_validate(_create(root_volume_size_gib=20))


def test_volume_from_image_accepts_safe_user_data_without_serializing_it() -> None:
    request = InstanceCreateRequest.model_validate(
        _create(
            boot_source=InstanceBootSource.VOLUME_FROM_IMAGE,
            root_volume_size_gib=20,
            user_data="cloud-config-private",
        )
    )
    assert request.user_data == "cloud-config-private"


def test_non_create_command_requires_provider_instance_id() -> None:
    with pytest.raises(ValidationError, match="provider resource id"):
        InstanceCommandPayload.model_validate({"action": InstanceAction.START})
