"""Typed provider inventory persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin


class InventoryResourceMixin(TimestampMixin, VersionMixin):
    """Columns shared by every provider-neutral inventory resource."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False
    )
    provider_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ACTIVE"
    )
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    provider_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    @classmethod
    def common_constraints(cls, table_name: str) -> tuple[object, ...]:
        return (
            UniqueConstraint(
                "provider_connection_id",
                "provider_resource_id",
                name=f"uq_{table_name}_connection_provider_resource",
            ),
            CheckConstraint(
                "lifecycle_state IN ('ACTIVE', 'DELETED', 'UNKNOWN')",
                name=f"ck_{table_name}_lifecycle_state",
            ),
            CheckConstraint("version > 0", name=f"ck_{table_name}_version_positive"),
            Index(f"ix_{table_name}_provider_connection_id", "provider_connection_id"),
            Index(f"ix_{table_name}_lifecycle_state", "lifecycle_state"),
            Index(f"ix_{table_name}_name", "name"),
        )


class Region(Base, InventoryResourceMixin):
    __tablename__ = "regions"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    parent_region_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )


class IdentityDomain(Base, InventoryResourceMixin):
    __tablename__ = "identity_domains"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Project(Base, InventoryResourceMixin):
    __tablename__ = "projects"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    domain_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_domain_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    owner_project_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class RoleAssignment(Base, InventoryResourceMixin):
    """Normalized Keystone role assignment (no principal credentials)."""

    __tablename__ = "role_assignments"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_provider_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_provider_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inherited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Quota(Base, InventoryResourceMixin):
    """A service quota snapshot. ``-1`` is represented by ``unlimited``."""

    __tablename__ = "quotas"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    limit_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_use: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unlimited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Flavor(Base, InventoryResourceMixin):
    __tablename__ = "flavors"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    vcpus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_mib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_disk_gib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ephemeral_disk_gib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swap_mib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_public: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Image(Base, InventoryResourceMixin):
    __tablename__ = "images"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    visibility: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_disk_gib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_ram_mib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Instance(Base, InventoryResourceMixin):
    __tablename__ = "instances"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    power_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    flavor_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boot_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    availability_zone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    addresses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    metadata_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Network(Base, InventoryResourceMixin):
    __tablename__ = "networks"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    admin_state_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shared: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    external: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mtu: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Subnet(Base, InventoryResourceMixin):
    __tablename__ = "subnets"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    network_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gateway_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enable_dhcp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dns_nameservers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    allocation_pools: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")


class Port(Base, InventoryResourceMixin):
    __tablename__ = "ports"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    network_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_state_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fixed_ips: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    device_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    security_group_provider_resource_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class Router(Base, InventoryResourceMixin):
    __tablename__ = "routers"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    admin_state_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    external_gateway_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    routes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")


class RouterInterface(Base):
    __tablename__ = "router_interfaces"
    router_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("routers.id", ondelete="CASCADE"), primary_key=True
    )
    subnet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subnets.id", ondelete="RESTRICT"), primary_key=True
    )
    provider_router_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_subnet_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    port_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SecurityGroup(Base, InventoryResourceMixin):
    __tablename__ = "security_groups"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    stateful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class SecurityGroupRule(Base, InventoryResourceMixin):
    __tablename__ = "security_group_rules"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    security_group_provider_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    ethertype: Mapped[str | None] = mapped_column(String(16), nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    port_range_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_range_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_ip_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_group_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )


class FloatingIP(Base, InventoryResourceMixin):
    __tablename__ = "floating_ips"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    floating_network_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    floating_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fixed_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    port_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    router_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Volume(Base, InventoryResourceMixin):
    __tablename__ = "volumes"
    __table_args__ = InventoryResourceMixin.common_constraints(__tablename__)
    size_gib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bootable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    encrypted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    multiattach: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    availability_zone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")


class InstancePort(Base):
    __tablename__ = "instance_ports"
    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
    )
    port_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ports.id", ondelete="RESTRICT"), primary_key=True
    )
    provider_port_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device: Mapped[str | None] = mapped_column(String(255), nullable=True)


class InstanceVolume(Base):
    __tablename__ = "instance_volumes"
    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
    )
    volume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("volumes.id", ondelete="RESTRICT"), primary_key=True
    )
    provider_volume_resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boot_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_on_termination: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
