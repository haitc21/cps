from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_operations import (
    VolumeAttachmentOperation,
    VolumeOperation,
)


class VolumeOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: VolumeOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    size_gib: int | None = Field(default=None, ge=1, le=16384)
    volume_type_provider_resource_id: str | None = Field(default=None, max_length=255)
    availability_zone: str | None = Field(default=None, max_length=255)
    metadata: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class VolumeAttachmentOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: VolumeAttachmentOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    volume_provider_resource_id: str = Field(min_length=1, max_length=255)
    instance_provider_resource_id: str = Field(min_length=1, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
