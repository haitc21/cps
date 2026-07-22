"""Sprint 2 credential encryption foundation."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        legacy_count = bind.execute(sa.text("SELECT count(*) FROM credentials")).scalar_one()
        if legacy_count:
            raise RuntimeError(
                "credential migration requires an empty legacy table; no plaintext was migrated"
            )
    op.add_column("credentials", sa.Column("username_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("credentials", sa.Column("username_nonce", sa.LargeBinary(), nullable=True))
    op.add_column("credentials", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("credentials", "username")
    op.alter_column("credentials", "username_ciphertext", nullable=False)
    op.alter_column("credentials", "username_nonce", nullable=False)
    op.create_check_constraint(
        op.f("ck_credentials_username_nonce_length"),
        "credentials",
        "octet_length(username_nonce) = 12",
    )
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE operation_state ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_credentials_username_nonce_length"), "credentials", type_="check")
    op.drop_column("credentials", "rotated_at")
    op.drop_column("credentials", "username_nonce")
    op.drop_column("credentials", "username_ciphertext")
    op.add_column("credentials", sa.Column("username", sa.String(length=255), nullable=True))
    op.alter_column("credentials", "username", nullable=False)
