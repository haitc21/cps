"""Provider-neutral identity lifecycle, assignment, and quota requests."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.contracts.messages.resource_operations import ScopeKind


class IdentityOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DISABLE = "disable"
    DELETE = "delete"


class IdentityResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    resource_type: str = Field(pattern="^(domain|project)$")
    operation: IdentityOperation
    required_scope: ScopeKind
    provider_connection_id: UUID
    provider_resource_id: str | None = Field(default=None, max_length=255)
    domain_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_resource(self) -> IdentityResourceRequest:
        if self.operation is IdentityOperation.CREATE and not self.name:
            raise ValueError("name is required for create")
        if (
            self.resource_type == "project"
            and self.operation is IdentityOperation.CREATE
            and not self.domain_provider_resource_id
        ):
            raise ValueError("domain_provider_resource_id is required for project create")
        if self.operation is not IdentityOperation.CREATE and not self.provider_resource_id:
            raise ValueError("provider_resource_id is required for lifecycle operations")
        return self


class RoleAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    operation: str = Field(pattern="^(ensure|revoke)$")
    required_scope: ScopeKind
    provider_connection_id: UUID
    principal_type: str = Field(pattern="^(user|group)$")
    principal_provider_resource_id: str = Field(min_length=1, max_length=255)
    role_provider_resource_id: str = Field(min_length=1, max_length=255)
    scope_provider_resource_id: str | None = Field(default=None, max_length=255)


class QuotaValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_name: str = Field(min_length=1, max_length=128)
    limit: int = Field(ge=-1)


class QuotaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    operation: str = Field(pattern="^(read|update)$")
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_connection_id: UUID
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    service: str = Field(pattern="^(compute|network|block-storage)$")
    quotas: list[QuotaValue] = Field(min_length=1, max_length=128)


class IdentityOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    resource_type: str
    state: str
    provider_resource_id: str | None = None
    resource: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
