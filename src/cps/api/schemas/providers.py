"""Provider API DTOs and safe projections."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cps.infrastructure.db.models.enums import ProviderStatus


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider_type: str = Field(default="OPENSTACK", pattern="^OPENSTACK$")


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: ProviderStatus | None = None


class ProviderView(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    description: str | None
    status: ProviderStatus
    version: int
    created_at: datetime
    updated_at: datetime


class PageInfo(BaseModel):
    offset: int
    limit: int
    total: int


class ProviderPage(BaseModel):
    items: list[ProviderView]
    page: PageInfo
