"""VM lifecycle API request projections."""

from pydantic import BaseModel, Field

from cps.contracts.messages.instance import InstanceAction, InstanceCreateRequest


class InstanceActionRequest(BaseModel):
    action: InstanceAction
    reboot_type: str | None = Field(default=None, pattern="^(SOFT|HARD)$")


__all__ = ["InstanceActionRequest", "InstanceCreateRequest"]
