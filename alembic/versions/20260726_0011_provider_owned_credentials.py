"""Move the single provider credential out of the credentials table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0011"
down_revision: str | None = "20260726_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("username_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("providers", sa.Column("username_nonce", sa.LargeBinary(), nullable=True))
    op.add_column("providers", sa.Column("password_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("providers", sa.Column("password_nonce", sa.LargeBinary(), nullable=True))
    op.add_column("providers", sa.Column("encryption_key_version", sa.String(64), nullable=True))
    op.add_column(
        "providers",
        sa.Column("user_domain_name", sa.String(255), server_default="Default", nullable=True),
    )
    op.add_column("providers", sa.Column("credential_rotated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_providers_password_nonce_length", "providers", "octet_length(password_nonce) = 12"
    )
    op.create_check_constraint(
        "ck_providers_username_nonce_length", "providers", "octet_length(username_nonce) = 12"
    )
    op.create_unique_constraint(
        "uq_providers_encryption_key_version_password_nonce",
        "providers",
        ["encryption_key_version", "password_nonce"],
    )

    bind = op.get_bind()
    ambiguous = bind.execute(
        sa.text(
            """
            SELECT pc.provider_id
            FROM provider_connections pc
            GROUP BY pc.provider_id
            HAVING COUNT(DISTINCT pc.credential_id) > 1
            """
        )
    ).fetchall()
    if ambiguous:
        raise RuntimeError("cannot migrate provider with multiple credentials")

    bind.execute(
        sa.text(
            """
            UPDATE providers p
            SET username_ciphertext = c.username_ciphertext,
                username_nonce = c.username_nonce,
                password_ciphertext = c.password_ciphertext,
                password_nonce = c.password_nonce,
                encryption_key_version = c.encryption_key_version,
                user_domain_name = c.user_domain_name
            FROM provider_connections pc
            JOIN credentials c ON c.id = pc.credential_id
            WHERE pc.provider_id = p.id
            """
        )
    )
    op.alter_column("providers", "username_ciphertext", nullable=False)
    op.alter_column("providers", "username_nonce", nullable=False)
    op.alter_column("providers", "password_ciphertext", nullable=False)
    op.alter_column("providers", "password_nonce", nullable=False)
    op.alter_column("providers", "encryption_key_version", nullable=False)
    op.alter_column("providers", "user_domain_name", nullable=False)
    op.drop_constraint(
        "fk_provider_connections_credential_id_credentials",
        "provider_connections",
        type_="foreignkey",
    )
    op.drop_column("provider_connections", "credential_id")
    op.drop_table("credentials")


def downgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("username_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("password_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(64), nullable=False),
        sa.Column("user_domain_name", sa.String(255), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
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
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("provider_connections", sa.Column("credential_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_provider_connections_credential_id_credentials",
        "provider_connections",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT ON (p.id)
                p.id AS provider_id,
                p.username_ciphertext,
                p.username_nonce,
                p.password_ciphertext,
                p.password_nonce,
                p.encryption_key_version,
                p.user_domain_name,
                p.credential_rotated_at
            FROM providers p
            ORDER BY p.id
            """
        )
    ).mappings()
    import uuid

    for row in rows:
        credential_id = uuid.uuid4()
        bind.execute(
            sa.text(
                """
                INSERT INTO credentials
                (id, username_ciphertext, username_nonce, password_ciphertext,
                 password_nonce, encryption_key_version, user_domain_name,
                 rotated_at)
                VALUES (:id, :username_ciphertext, :username_nonce,
                        :password_ciphertext, :password_nonce,
                        :encryption_key_version, :user_domain_name,
                        :rotated_at)
                """
            ),
            {
                "id": credential_id,
                **dict(row),
                "rotated_at": row["credential_rotated_at"],
            },
        )
        bind.execute(
            sa.text(
                "UPDATE provider_connections "
                "SET credential_id = :credential_id "
                "WHERE provider_id = :provider_id"
            ),
            {"credential_id": credential_id, "provider_id": row["provider_id"]},
        )
    op.alter_column("provider_connections", "credential_id", nullable=False)
    op.drop_constraint(
        "uq_providers_encryption_key_version_password_nonce", "providers", type_="unique"
    )
    op.drop_constraint("ck_providers_username_nonce_length", "providers", type_="check")
    op.drop_constraint("ck_providers_password_nonce_length", "providers", type_="check")
    for column in (
        "credential_rotated_at",
        "user_domain_name",
        "encryption_key_version",
        "password_nonce",
        "password_ciphertext",
        "username_nonce",
        "username_ciphertext",
    ):
        op.drop_column("providers", column)
