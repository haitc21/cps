"""Sprint 9 network topology inventory and control projections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260724_0008"
down_revision = "20260724_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common(table: str) -> list[sa.Column[object]]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_resource_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("provider_status", sa.String(64)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("provider_created_at", sa.DateTime(timezone=True)),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "provider_attributes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
    ]


def upgrade() -> None:
    specs = {
        "routers": [
            sa.Column("admin_state_up", sa.Boolean),
            sa.Column(
                "external_gateway_info",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "routes", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
            ),
        ],
        "security_groups": [sa.Column("stateful", sa.Boolean)],
        "security_group_rules": [
            sa.Column("security_group_provider_resource_id", sa.String(255), nullable=False),
            sa.Column("direction", sa.String(16), nullable=False),
            sa.Column("ethertype", sa.String(16)),
            sa.Column("protocol", sa.String(32)),
            sa.Column("port_range_min", sa.Integer),
            sa.Column("port_range_max", sa.Integer),
            sa.Column("remote_ip_prefix", sa.String(64)),
            sa.Column("remote_group_provider_resource_id", sa.String(255)),
        ],
        "floating_ips": [
            sa.Column("floating_network_provider_resource_id", sa.String(255)),
            sa.Column("floating_ip", sa.String(64)),
            sa.Column("fixed_ip", sa.String(64)),
            sa.Column("port_provider_resource_id", sa.String(255)),
            sa.Column("router_provider_resource_id", sa.String(255)),
            sa.Column("status", sa.String(32)),
        ],
    }
    for table, cols in specs.items():
        op.create_table(table, *_common(table), *cols)
        op.create_index(f"ix_{table}_provider_connection_id", table, ["provider_connection_id"])
        op.create_index(f"ix_{table}_lifecycle_state", table, ["lifecycle_state"])
        op.create_index(f"ix_{table}_name", table, ["name"])
    op.create_table(
        "router_interfaces",
        sa.Column(
            "router_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "subnet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subnets.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("provider_router_resource_id", sa.String(255), nullable=False),
        sa.Column("provider_subnet_resource_id", sa.String(255), nullable=False),
        sa.Column("port_provider_resource_id", sa.String(255)),
    )


def downgrade() -> None:
    op.drop_table("router_interfaces")
    for table in ("floating_ips", "security_group_rules", "security_groups", "routers"):
        op.drop_table(table)
