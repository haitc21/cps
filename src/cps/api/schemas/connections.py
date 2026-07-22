"""Safe provider connection DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cps.infrastructure.db.models.enums import ConnectionStatus


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_id: uuid.UUID
    auth_url: str = Field(min_length=1, max_length=2048)
    project_name: str = Field(min_length=1, max_length=255)
    project_domain_name: str = Field(default="Default", min_length=1, max_length=255)
    region_name: str = Field(min_length=1, max_length=255)
    interface: str = Field(default="public", pattern="^(public|internal|admin)$")
    verify_tls: bool = True
    ca_cert_pem: str | None = Field(default=None, max_length=32768)


class ConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    credential_id: uuid.UUID | None = None
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
