"""Credential API DTOs; secret material is accepted only on writes."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=4096)
    user_domain_name: str = Field(default="Default", min_length=1, max_length=255)


class CredentialPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=4096)
    user_domain_name: str | None = Field(default=None, min_length=1, max_length=255)


class CredentialMetadataView(BaseModel):
    id: uuid.UUID
    user_domain_name: str
    version: int
    rotated_at: datetime | None
    created_at: datetime
    updated_at: datetime
