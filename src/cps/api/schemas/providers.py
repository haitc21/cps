"""Provider API DTOs and safe projections."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider_type: str = Field(default="OPENSTACK", pattern="^OPENSTACK$")
    auth_url: str = Field(min_length=1, max_length=2048)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=4096)
    user_domain_name: str = Field(default="Default", min_length=1, max_length=255)
    region_name: str = Field(min_length=1, max_length=255)
    interface: str = Field(default="public", pattern="^(public|internal|admin)$")
    verify_tls: bool = True
    ca_cert_pem: str | None = Field(default=None, max_length=32768)


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: ProviderStatus | None = None
    auth_url: str | None = Field(default=None, min_length=1, max_length=2048)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=4096)
    user_domain_name: str | None = Field(default=None, min_length=1, max_length=255)
    region_name: str | None = Field(default=None, min_length=1, max_length=255)
    interface: str | None = Field(default=None, pattern="^(public|internal|admin)$")
    verify_tls: bool | None = None
    ca_cert_pem: str | None = Field(default=None, max_length=32768)


class ProviderView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    name: str
    provider_type: str
    description: str | None
    status: ProviderStatus
    version: int
    created_at: datetime
    updated_at: datetime
    auth_url: str
    user_domain_name: str
    region_name: str
    interface: str
    verify_tls: bool
    has_custom_ca: bool
    connection_status: ConnectionStatus


class PageInfo(BaseModel):
    offset: int
    limit: int
    total: int


class ProviderPage(BaseModel):
    items: list[ProviderView]
    page: PageInfo
