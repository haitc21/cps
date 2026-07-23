"""Sprint 3 inventory sync and batch persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0004"
down_revision: str | None = "20260723_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "inventory_syncs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "operation_id",
            UUID,
            sa.ForeignKey("operations.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "provider_connection_id",
            UUID,
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sync_type", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="QUEUED"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "expected_collections", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "completed_collections", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "skipped_collections", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "failed_collections", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("error_summary", JSONB),
        sa.CheckConstraint(
            "sync_type IN ('FULL', 'TARGETED')", name="ck_inventory_syncs_sync_type_allowed"
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT')",
            name="ck_inventory_syncs_state_allowed",
        ),
    )
    op.create_index(
        "ix_inventory_syncs_connection_state",
        "inventory_syncs",
        ["provider_connection_id", "state"],
    )
    op.create_table(
        "inventory_batches",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "sync_id", UUID, sa.ForeignKey("inventory_syncs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("is_last", sa.Boolean, nullable=False),
        sa.Column("collection_status", sa.String(32), nullable=False),
        sa.Column("item_count", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("processing_state", sa.String(16), nullable=False, server_default="RECEIVED"),
        sa.Column("processing_error", sa.Text),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "sync_id",
            "resource_type",
            "sequence",
            name="uq_inventory_batches_sync_resource_sequence",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_inventory_batches_sequence_positive"),
        sa.CheckConstraint("item_count >= 0", name="ck_inventory_batches_item_count_nonnegative"),
    )
    op.create_index("ix_inventory_batches_sync_id", "inventory_batches", ["sync_id"])


def downgrade() -> None:
    op.drop_table("inventory_batches")
    op.drop_index("ix_inventory_syncs_connection_state", table_name="inventory_syncs")
    op.drop_table("inventory_syncs")
