from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.messages.keypair_operations import KeypairOperation
from cps.contracts.messages.resource_operations import ScopeKind


class KeypairOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: KeypairOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    public_key: str | None = Field(default=None, min_length=32, max_length=16384)
    parameters: dict[str, Any] = Field(default_factory=dict)
