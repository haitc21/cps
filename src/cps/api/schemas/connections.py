"""Safe provider connection DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_id: uuid.UUID
    scope_kind: ConnectionScopeKind = ConnectionScopeKind.PROJECT
    scope_domain_provider_resource_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    scope_project_provider_resource_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    auth_url: str = Field(min_length=1, max_length=2048)
    project_name: str = Field(min_length=1, max_length=255)
    project_domain_name: str = Field(default="Default", min_length=1, max_length=255)
    region_name: str = Field(min_length=1, max_length=255)
    interface: str = Field(default="public", pattern="^(public|internal|admin)$")
    verify_tls: bool = True
    ca_cert_pem: str | None = Field(default=None, max_length=32768)

    @model_validator(mode="after")
    def validate_scope(self) -> ConnectionCreate:
        if (
            self.scope_kind is ConnectionScopeKind.SYSTEM
            and self.scope_project_provider_resource_id
        ):
            raise ValueError("SYSTEM connections cannot bind a project")
        if (
            self.scope_kind is ConnectionScopeKind.PROJECT
            and not self.scope_project_provider_resource_id
        ):
            # Legacy callers identify the project by project_name; the explicit
            # provider ID becomes available after validation/inventory.
            return self
        return self


class ConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    credential_id: uuid.UUID | None = None
    scope_kind: ConnectionScopeKind | None = None
    scope_domain_provider_resource_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    scope_project_provider_resource_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    auth_url: str | None = Field(default=None, min_length=1, max_length=2048)
    project_name: str | None = Field(default=None, min_length=1, max_length=255)
    project_domain_name: str | None = Field(default=None, min_length=1, max_length=255)
    region_name: str | None = Field(default=None, min_length=1, max_length=255)
    interface: str | None = Field(default=None, pattern="^(public|internal|admin)$")
    verify_tls: bool | None = None
    ca_cert_pem: str | None = Field(default=None, max_length=32768)
    status: ConnectionStatus | None = None


class ConnectionView(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    scope_kind: ConnectionScopeKind
    scope_domain_provider_resource_id: str | None
    scope_project_provider_resource_id: str | None
    project_name: str
    project_domain_name: str
    region_name: str
    auth_url: str
    interface: str
    verify_tls: bool
    has_custom_ca: bool
    status: ConnectionStatus
    capabilities: dict[str, object] | None
    validation_error: dict[str, object] | None
    validated_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class PageInfo(BaseModel):
    offset: int
    limit: int
    total: int


class ConnectionPage(BaseModel):
    items: list[ConnectionView]
    page: PageInfo
