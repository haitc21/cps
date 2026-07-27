"""CPS-1501 typed project-owned volume inventory fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260727_0013"
down_revision: str | None = "20260726_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("volumes", sa.Column("volume_type_provider_resource_id", sa.String(255)))
    op.add_column("volumes", sa.Column("root", sa.Boolean))
    op.add_column(
        "volumes",
        sa.Column(
            "metadata_values",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("volumes", "metadata_values")
    op.drop_column("volumes", "root")
    op.drop_column("volumes", "volume_type_provider_resource_id")
