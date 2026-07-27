from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_snapshot_operations import VolumeSnapshotOperation


class VolumeSnapshotOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: VolumeSnapshotOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_resource_id: str | None = Field(default=None, max_length=255)
    volume_provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    resource_type: str = Field(default="snapshot", pattern=r"^snapshot$")
    parameters: dict[str, Any] = Field(default_factory=dict)
