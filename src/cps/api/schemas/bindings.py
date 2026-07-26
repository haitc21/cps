"""API DTOs for explicit provider identity ownership bindings."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IdentityDomainBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)


class IdentityProjectBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: str = Field(min_length=1, max_length=255)
    workspace_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)


class IdentityBindingView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: uuid.UUID
    provider_id: uuid.UUID
    provider_type: str
    binding_kind: str
    org_id: str
    workspace_id: str | None
    provider_resource_id: str | None
    provider_resource_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    version: int


class IdentityBindingAccepted(BaseModel):
    binding: IdentityBindingView
    operation: object
    status_url: str
