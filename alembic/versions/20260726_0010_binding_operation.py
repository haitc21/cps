"""Store the durable operation associated with a pending identity binding."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "identity_bindings",
        sa.Column(
            "operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operations.id", ondelete="RESTRICT"),
        ),
    )


def downgrade() -> None:
    op.drop_column("identity_bindings", "operation_id")
