"""Sprint 7 scoped connections and identity-domain inventory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0006"
down_revision: str | None = "20260723_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scope = postgresql.ENUM("SYSTEM", "DOMAIN", "PROJECT", name="connection_scope_kind")
    scope.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "provider_connections",
        sa.Column("scope_kind", scope, nullable=False, server_default="PROJECT"),
    )
    op.add_column(
        "provider_connections", sa.Column("scope_domain_provider_resource_id", sa.String(255))
    )
    op.add_column(
        "provider_connections", sa.Column("scope_project_provider_resource_id", sa.String(255))
    )
    op.create_index("ix_provider_connections_scope_kind", "provider_connections", ["scope_kind"])

    def common(table: str) -> list[sa.Column[object]]:
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
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
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
        ]

    op.create_table(
        "identity_domains", *common("identity_domains"), sa.Column("enabled", sa.Boolean)
    )
    op.create_index(
        "ix_identity_domains_provider_connection_id", "identity_domains", ["provider_connection_id"]
    )
    op.create_index("ix_identity_domains_lifecycle_state", "identity_domains", ["lifecycle_state"])
    op.create_index("ix_identity_domains_name", "identity_domains", ["name"])
    op.add_column("projects", sa.Column("owner_domain_provider_resource_id", sa.String(255)))
    op.add_column("projects", sa.Column("owner_project_provider_resource_id", sa.String(255)))


def downgrade() -> None:
    op.drop_column("projects", "owner_project_provider_resource_id")
    op.drop_column("projects", "owner_domain_provider_resource_id")
    op.drop_table("identity_domains")
    op.drop_index("ix_provider_connections_scope_kind", table_name="provider_connections")
    op.drop_column("provider_connections", "scope_project_provider_resource_id")
    op.drop_column("provider_connections", "scope_domain_provider_resource_id")
    op.drop_column("provider_connections", "scope_kind")
    postgresql.ENUM(name="connection_scope_kind").drop(op.get_bind(), checkfirst=True)
