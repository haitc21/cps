"""CPS-1601 typed volume snapshot inventory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260727_0014"
down_revision: str | None = "20260727_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "volume_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_resource_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider_status", sa.String(64), nullable=True),
        sa.Column("lifecycle_state", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_id", sa.Uuid(), nullable=True),
        sa.Column("provider_attributes", JSONB, server_default="{}", nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("project_provider_resource_id", sa.String(255), nullable=True),
        sa.Column("volume_provider_resource_id", sa.String(255), nullable=True),
        sa.Column("size_gib", sa.Integer(), nullable=True),
        sa.Column("metadata_values", JSONB, server_default="{}", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_connection_id"], ["provider_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_connection_id",
            "provider_resource_id",
            name="uq_volume_snapshots_connection_provider_resource",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE', 'DELETED', 'UNKNOWN')",
            name="ck_volume_snapshots_lifecycle_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_volume_snapshots_version_positive"),
    )
    op.create_index(
        "ix_volume_snapshots_provider_connection_id", "volume_snapshots", ["provider_connection_id"]
    )
    op.create_index("ix_volume_snapshots_lifecycle_state", "volume_snapshots", ["lifecycle_state"])
    op.create_index("ix_volume_snapshots_name", "volume_snapshots", ["name"])


def downgrade() -> None:
    op.drop_table("volume_snapshots")
