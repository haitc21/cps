"""Sprint 8 identity lifecycle projections, role assignments, and quotas."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0007"
down_revision: str | None = "20260724_0006"
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
    op.create_table(
        "role_assignments",
        *_common("role_assignments"),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_provider_resource_id", sa.String(255), nullable=False),
        sa.Column("role_provider_resource_id", sa.String(255), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_provider_resource_id", sa.String(255)),
        sa.Column("inherited", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_role_assignments_provider_connection_id", "role_assignments", ["provider_connection_id"]
    )
    op.create_index("ix_role_assignments_lifecycle_state", "role_assignments", ["lifecycle_state"])
    op.create_index("ix_role_assignments_name", "role_assignments", ["name"])
    op.create_table(
        "quotas",
        *_common("quotas"),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("resource_name", sa.String(128), nullable=False),
        sa.Column("limit_value", sa.BigInteger),
        sa.Column("in_use", sa.BigInteger),
        sa.Column("unlimited", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_quotas_provider_connection_id", "quotas", ["provider_connection_id"])
    op.create_index("ix_quotas_lifecycle_state", "quotas", ["lifecycle_state"])
    op.create_index("ix_quotas_name", "quotas", ["name"])


def downgrade() -> None:
    op.drop_table("quotas")
    op.drop_table("role_assignments")
