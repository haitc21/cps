"""VM lifecycle API request projections."""

from pydantic import BaseModel, Field

from cps.contracts.messages.instance import InstanceAction, InstanceCreateRequest


class InstanceActionRequest(BaseModel):
    action: InstanceAction
    reboot_type: str | None = Field(default=None, pattern="^(SOFT|HARD)$")
    resize_flavor_provider_resource_id: str | None = Field(default=None, max_length=255)
    rebuild_image_provider_resource_id: str | None = Field(default=None, max_length=255)


__all__ = ["InstanceActionRequest", "InstanceCreateRequest"]
