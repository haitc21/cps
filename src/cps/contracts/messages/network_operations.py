"""Provider-neutral network topology lifecycle commands."""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.contracts.messages.resource_operations import ScopeKind


class NetworkResourceType(StrEnum):
    NETWORK = "network"
    SUBNET = "subnet"
    ROUTER = "router"
    ROUTER_INTERFACE = "router-interface"
    PORT = "port"
    SECURITY_GROUP = "security-group"
    SECURITY_GROUP_RULE = "security-group-rule"
    FLOATING_IP = "floating-ip"


class NetworkOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ENSURE = "ensure"
    REMOVE = "remove"
    ALLOCATE = "allocate"
    ASSOCIATE = "associate"
    DISASSOCIATE = "disassociate"
    RELEASE = "release"


class NetworkOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    resource_type: NetworkResourceType
    operation: NetworkOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_connection_id: UUID
    provider_resource_id: str | None = Field(default=None, max_length=255)
    network_provider_resource_id: str | None = Field(default=None, max_length=255)
    subnet_provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    port_provider_resource_id: str | None = Field(default=None, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relationships(self) -> NetworkOperationRequest:
        if (
            self.operation
            in {
                NetworkOperation.UPDATE,
                NetworkOperation.DELETE,
                NetworkOperation.REMOVE,
                NetworkOperation.ASSOCIATE,
                NetworkOperation.DISASSOCIATE,
                NetworkOperation.RELEASE,
            }
            and not self.provider_resource_id
            and self.resource_type is not NetworkResourceType.ROUTER_INTERFACE
        ):
            raise ValueError("provider_resource_id is required for lifecycle operations")
        if (
            self.resource_type is NetworkResourceType.SUBNET
            and self.operation is NetworkOperation.CREATE
        ):
            cidr = self.parameters.get("cidr")
            if not isinstance(cidr, str):
                raise ValueError("subnet create requires cidr")
            try:
                ipaddress.ip_network(cidr, strict=True)
            except ValueError as exc:
                raise ValueError("cidr must be a valid network") from exc
        if self.resource_type is NetworkResourceType.ROUTER_INTERFACE and self.operation in {
            NetworkOperation.ENSURE,
            NetworkOperation.REMOVE,
        }:
            if not self.subnet_provider_resource_id:
                raise ValueError("router interface requires subnet_provider_resource_id")
        if (
            self.resource_type is NetworkResourceType.FLOATING_IP
            and self.operation is NetworkOperation.ALLOCATE
        ):
            if not self.network_provider_resource_id:
                raise ValueError("floating IP allocation requires external network")
        return self


class NetworkOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    resource_type: NetworkResourceType
    state: str
    provider_resource_id: str | None = None
    resource: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
