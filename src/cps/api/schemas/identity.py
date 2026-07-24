from __future__ import annotations

from pydantic import BaseModel, Field

from cps.contracts.messages.resource_operations import ScopeKind


class IdentityLifecycleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None
    domain_provider_resource_id: str | None = Field(default=None, max_length=255)
    provider_resource_id: str | None = Field(default=None, max_length=255)


class RoleAssignmentRequestBody(BaseModel):
    operation: str = Field(pattern="^(ensure|revoke)$")
    principal_type: str = Field(pattern="^(user|group)$")
    principal_provider_resource_id: str = Field(min_length=1, max_length=255)
    role_provider_resource_id: str = Field(min_length=1, max_length=255)
    scope_kind: ScopeKind = ScopeKind.PROJECT
    scope_provider_resource_id: str | None = Field(default=None, max_length=255)


class QuotaUpdate(BaseModel):
    resource_name: str = Field(min_length=1, max_length=128)
    limit: int = Field(ge=-1)


class QuotaRequestBody(BaseModel):
    operation: str = Field(pattern="^(read|update)$")
    service: str = Field(pattern="^(compute|network|block-storage)$")
    quotas: list[QuotaUpdate] = Field(min_length=1, max_length=128)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
