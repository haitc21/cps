"""Sprint 3 targeted refresh target identity."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0005"
down_revision: str | None = "20260723_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inventory_syncs", sa.Column("target_resource_type", sa.String(32)))
    op.add_column("inventory_syncs", sa.Column("target_provider_resource_id", sa.String(255)))


def downgrade() -> None:
    op.drop_column("inventory_syncs", "target_provider_resource_id")
    op.drop_column("inventory_syncs", "target_resource_type")
