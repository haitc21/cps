"""Sprint 3 typed inventory schema foundation."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0003"
down_revision: str | None = "20260722_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def _common(table: str) -> list[sa.Column[object]]:
    return [
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "provider_connection_id",
            UUID,
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_resource_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("provider_status", sa.String(64), nullable=True),
        sa.Column("lifecycle_state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_id", UUID, nullable=True),
        sa.Column(
            "provider_attributes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "provider_connection_id",
            "provider_resource_id",
            name=f"uq_{table}_connection_provider_resource",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE', 'DELETED', 'UNKNOWN')",
            name=f"ck_{table}_lifecycle_state",
        ),
        sa.CheckConstraint("version > 0", name=f"ck_{table}_version_positive"),
    ]


def upgrade() -> None:
    op.create_table(
        "regions",
        *_common("regions"),
        sa.Column("parent_region_provider_resource_id", sa.String(255)),
    )
    op.create_table(
        "projects",
        *_common("projects"),
        sa.Column("domain_provider_resource_id", sa.String(255)),
        sa.Column("domain_name", sa.String(255)),
        sa.Column("enabled", sa.Boolean),
    )
    op.create_table(
        "flavors",
        *_common("flavors"),
        sa.Column("vcpus", sa.Integer),
        sa.Column("ram_mib", sa.Integer),
        sa.Column("root_disk_gib", sa.Integer),
        sa.Column("ephemeral_disk_gib", sa.Integer),
        sa.Column("swap_mib", sa.Integer),
        sa.Column("is_public", sa.Boolean),
        sa.Column("enabled", sa.Boolean),
    )
    op.create_table(
        "images",
        *_common("images"),
        sa.Column("visibility", sa.String(32)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("min_disk_gib", sa.Integer),
        sa.Column("min_ram_mib", sa.Integer),
        sa.Column("disk_format", sa.String(32)),
        sa.Column("checksum", sa.String(128)),
    )
    op.create_table(
        "instances",
        *_common("instances"),
        sa.Column("power_state", sa.String(32)),
        sa.Column("flavor_provider_resource_id", sa.String(255)),
        sa.Column("image_provider_resource_id", sa.String(255)),
        sa.Column("boot_source", sa.String(32)),
        sa.Column("availability_zone", sa.String(255)),
        sa.Column("addresses", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_values", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("launched_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "networks",
        *_common("networks"),
        sa.Column("admin_state_up", sa.Boolean),
        sa.Column("shared", sa.Boolean),
        sa.Column("external", sa.Boolean),
        sa.Column("mtu", sa.Integer),
    )
    op.create_table(
        "subnets",
        *_common("subnets"),
        sa.Column("network_provider_resource_id", sa.String(255)),
        sa.Column("cidr", sa.String(64)),
        sa.Column("ip_version", sa.Integer),
        sa.Column("gateway_ip", sa.String(64)),
        sa.Column("enable_dhcp", sa.Boolean),
        sa.Column("dns_nameservers", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("allocation_pools", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_table(
        "ports",
        *_common("ports"),
        sa.Column("network_provider_resource_id", sa.String(255)),
        sa.Column("admin_state_up", sa.Boolean),
        sa.Column("mac_address", sa.String(64)),
        sa.Column("fixed_ips", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("device_provider_resource_id", sa.String(255)),
        sa.Column("device_owner", sa.String(255)),
        sa.Column(
            "security_group_provider_resource_ids",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_table(
        "volumes",
        *_common("volumes"),
        sa.Column("size_gib", sa.Integer),
        sa.Column("volume_type", sa.String(255)),
        sa.Column("bootable", sa.Boolean),
        sa.Column("encrypted", sa.Boolean),
        sa.Column("multiattach", sa.Boolean),
        sa.Column("availability_zone", sa.String(255)),
        sa.Column("attachments", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_table(
        "instance_ports",
        sa.Column(
            "instance_id", UUID, sa.ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "port_id", UUID, sa.ForeignKey("ports.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("provider_port_resource_id", sa.String(255), nullable=False),
        sa.Column("device", sa.String(255)),
        sa.UniqueConstraint("instance_id", "port_id", name="uq_instance_ports_instance_port"),
    )
    op.create_table(
        "instance_volumes",
        sa.Column(
            "instance_id", UUID, sa.ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "volume_id", UUID, sa.ForeignKey("volumes.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("provider_volume_resource_id", sa.String(255), nullable=False),
        sa.Column("device", sa.String(255)),
        sa.Column("boot_index", sa.Integer),
        sa.Column("delete_on_termination", sa.Boolean),
        sa.UniqueConstraint("instance_id", "volume_id", name="uq_instance_volumes_instance_volume"),
    )
    for table in (
        "regions",
        "projects",
        "flavors",
        "images",
        "instances",
        "networks",
        "subnets",
        "ports",
        "volumes",
    ):
        op.create_index(f"ix_{table}_provider_connection_id", table, ["provider_connection_id"])
        op.create_index(f"ix_{table}_lifecycle_state", table, ["lifecycle_state"])
        op.create_index(f"ix_{table}_name", table, ["name"])


def downgrade() -> None:
    for table in (
        "instance_volumes",
        "instance_ports",
        "volumes",
        "ports",
        "subnets",
        "networks",
        "instances",
        "images",
        "flavors",
        "projects",
        "regions",
    ):
        op.drop_table(table)
