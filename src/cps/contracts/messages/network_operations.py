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
                network = ipaddress.ip_network(cidr, strict=True)
            except ValueError as exc:
                raise ValueError("cidr must be a valid network") from exc
            gateway = self.parameters.get("gateway_ip")
            if gateway is not None and ipaddress.ip_address(str(gateway)) not in network:
                raise ValueError("gateway_ip must be inside subnet cidr")
            for pool in self.parameters.get("allocation_pools", []) or []:
                if not isinstance(pool, dict) or not pool.get("start") or not pool.get("end"):
                    raise ValueError("invalid allocation pool")
                start = ipaddress.ip_address(str(pool["start"]))
                end = ipaddress.ip_address(str(pool["end"]))
                if (
                    start.version != end.version
                    or start not in network
                    or end not in network
                    or int(start) > int(end)
                ):
                    raise ValueError("allocation pool must be inside subnet cidr")
        if (
            self.resource_type is NetworkResourceType.NETWORK
            and self.operation in {NetworkOperation.CREATE, NetworkOperation.UPDATE}
            and any(
                self.parameters.get(key) is True
                for key in ("external", "is_router_external", "router:external")
            )
        ):
            raise ValueError("external network mutation is administrator-only")
        if (
            self.resource_type is NetworkResourceType.SECURITY_GROUP_RULE
            and self.operation is NetworkOperation.CREATE
        ):
            direction = self.parameters.get("direction")
            if direction not in {"ingress", "egress"}:
                raise ValueError("direction must be ingress or egress")
            minimum = self.parameters.get("port_range_min")
            maximum = self.parameters.get("port_range_max")
            if (minimum is None) != (maximum is None):
                raise ValueError("port range requires both minimum and maximum")
            if minimum is not None and (
                not isinstance(minimum, int)
                or not isinstance(maximum, int)
                or minimum < 1
                or maximum > 65535
                or minimum > maximum
            ):
                raise ValueError("invalid port range")
            remote_prefix = self.parameters.get("remote_ip_prefix")
            if remote_prefix is not None:
                try:
                    remote_network = ipaddress.ip_network(str(remote_prefix), strict=False)
                except ValueError as exc:
                    raise ValueError("remote_ip_prefix must be a valid network") from exc
                if direction == "ingress" and remote_network.prefixlen == 0:
                    raise ValueError("public ingress rules require administrator policy")
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
        if (
            self.resource_type is NetworkResourceType.FLOATING_IP
            and self.operation is NetworkOperation.ASSOCIATE
        ):
            if not self.port_provider_resource_id:
                raise ValueError("floating IP associate requires port_provider_resource_id")
        return self


class NetworkOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    resource_type: NetworkResourceType
    state: str
    provider_resource_id: str | None = None
    resource: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
