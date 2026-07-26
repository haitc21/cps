"""Sprint 10 explicit CMP identity ownership bindings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0009"
down_revision: str | None = "20260724_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("binding_kind", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.String(255)),
        sa.Column("provider_resource_id", sa.String(255)),
        sa.Column("provider_resource_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("last_error_code", sa.String(128)),
        sa.Column("last_error_message", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "binding_kind IN ('OPENSTACK_DOMAIN', 'OPENSTACK_PROJECT')",
            name="identity_binding_kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'FAILED', 'DELETED')",
            name="identity_binding_status_valid",
        ),
        sa.CheckConstraint(
            "(binding_kind = 'OPENSTACK_DOMAIN' AND workspace_id IS NULL) OR "
            "(binding_kind = 'OPENSTACK_PROJECT' AND workspace_id IS NOT NULL)",
            name="identity_binding_workspace_shape",
        ),
    )
    op.create_index(
        "uq_identity_binding_domain_owner",
        "identity_bindings",
        ["provider_id", "org_id"],
        unique=True,
        postgresql_where=sa.text("binding_kind = 'OPENSTACK_DOMAIN'"),
    )
    op.create_index(
        "uq_identity_binding_project_owner",
        "identity_bindings",
        ["provider_id", "org_id", "workspace_id"],
        unique=True,
        postgresql_where=sa.text("binding_kind = 'OPENSTACK_PROJECT'"),
    )
    op.create_index(
        "uq_identity_binding_provider_resource",
        "identity_bindings",
        ["provider_id", "binding_kind", "provider_resource_id"],
        unique=True,
        postgresql_where=sa.text("provider_resource_id IS NOT NULL"),
    )
    op.create_index("ix_identity_bindings_provider_id", "identity_bindings", ["provider_id"])
    op.create_index("ix_identity_bindings_status", "identity_bindings", ["status"])


def downgrade() -> None:
    op.drop_table("identity_bindings")
