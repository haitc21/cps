from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.contracts.messages.resource_operations import ScopeKind


class VolumeSnapshotOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class VolumeSnapshotOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    resource_type: str = Field(default="snapshot", pattern=r"^snapshot$")
    operation: VolumeSnapshotOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_connection_id: UUID
    provider_resource_id: str | None = Field(default=None, max_length=255)
    volume_provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_request(self) -> VolumeSnapshotOperationRequest:
        if self.operation is VolumeSnapshotOperation.CREATE:
            if not self.name or not self.volume_provider_resource_id:
                raise ValueError("snapshot create requires name and volume_provider_resource_id")
        elif not self.provider_resource_id:
            raise ValueError("snapshot update/delete requires provider_resource_id")
        if self.operation is VolumeSnapshotOperation.UPDATE and not any(
            value is not None for value in (self.name, self.parameters.get("description"))
        ):
            raise ValueError("snapshot update requires a mutable field")
        return self
