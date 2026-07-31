"""CPS-1703 availability-zone and volume-type catalog inventory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260731_0016"
down_revision: str | None = "20260727_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_catalog_table(
    name: str,
    *,
    typed_columns: tuple[sa.Column[object], ...],
) -> None:
    op.create_table(
        name,
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
        *typed_columns,
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_connection_id",
            "provider_resource_id",
            name=f"uq_{name}_connection_provider_resource",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE', 'DELETED', 'UNKNOWN')",
            name=f"ck_{name}_lifecycle_state",
        ),
        sa.CheckConstraint("version > 0", name=f"ck_{name}_version_positive"),
    )
    op.create_index(f"ix_{name}_provider_connection_id", name, ["provider_connection_id"])
    op.create_index(f"ix_{name}_lifecycle_state", name, ["lifecycle_state"])
    op.create_index(f"ix_{name}_name", name, ["name"])


def upgrade() -> None:
    _create_catalog_table(
        "availability_zones",
        typed_columns=(sa.Column("available", sa.Boolean(), nullable=True),),
    )
    _create_catalog_table(
        "volume_types",
        typed_columns=(sa.Column("is_public", sa.Boolean(), nullable=True),),
    )


def downgrade() -> None:
    op.drop_table("volume_types")
    op.drop_table("availability_zones")
