from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cps.contracts.messages.network_operations import NetworkOperation, NetworkResourceType
from cps.contracts.messages.resource_operations import ScopeKind


class NetworkOperationBody(BaseModel):
    resource_type: NetworkResourceType
    operation: NetworkOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_resource_id: str | None = Field(default=None, max_length=255)
    network_provider_resource_id: str | None = Field(default=None, max_length=255)
    subnet_provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    port_provider_resource_id: str | None = Field(default=None, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
