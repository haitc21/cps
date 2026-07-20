"""initial persistence

Revision ID: 20260720_0001
Revises:
Create Date: 2026-07-20 14:20:05.875569

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260720_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_TYPES = (
    "inbox_process_state",
    "outbox_publish_state",
    "operation_state",
    "connection_status",
    "provider_status",
)


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("password_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=64), nullable=False),
        sa.Column(
            "user_domain_name", sa.String(length=255), server_default="Default", nullable=False
        ),
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
        sa.CheckConstraint(
            "octet_length(password_nonce) = 12", name=op.f("ck_credentials_password_nonce_length")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_credentials_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
        sa.UniqueConstraint(
            "encryption_key_version",
            "password_nonce",
            name="uq_credentials_encryption_key_version_password_nonce",
        ),
    )
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer_name", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "process_state",
            sa.Enum("RECEIVED", "PROCESSED", name="inbox_process_state"),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_messages")),
        sa.UniqueConstraint(
            "consumer_name",
            "message_id",
            name="uq_inbox_messages_consumer_message",
        ),
    )
    op.create_index(
        "ix_inbox_messages_process_state", "inbox_messages", ["process_state"], unique=False
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(length=128), nullable=False),
        sa.Column("routing_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "publish_state",
            sa.Enum("PENDING", "CLAIMED", "PUBLISHED", "FAILED", name="outbox_publish_state"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "(publish_state = 'CLAIMED' AND claimed_by IS NOT NULL "
            "AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) "
            "OR (publish_state != 'CLAIMED' AND claimed_by IS NULL "
            "AND claim_token IS NULL AND claim_expires_at IS NULL)",
            name=op.f("ck_outbox_messages_claim_fields"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_outbox_messages_attempt_count_nonnegative")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_outbox_messages_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
        sa.UniqueConstraint("message_id", name=op.f("uq_outbox_messages_message_id")),
    )
    op.create_index(
        "ix_outbox_messages_claim_expiry",
        "outbox_messages",
        ["claim_expires_at"],
        unique=False,
        postgresql_where=sa.text("publish_state = 'CLAIMED'"),
    )
    op.create_index(
        "ix_outbox_messages_publish_pending",
        "outbox_messages",
        ["publish_state", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("publish_state = 'PENDING'"),
    )
    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_type", sa.String(length=32), server_default="OPENSTACK", nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DISABLED", name="provider_status"),
            server_default="ACTIVE",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "provider_type = 'OPENSTACK'", name=op.f("ck_providers_provider_type_openstack")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_providers_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_providers")),
    )
    op.create_index("ix_providers_name", "providers", ["name"], unique=False)
    op.create_index("ix_providers_status", "providers", ["status"], unique=False)
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column(
            "project_domain_name", sa.String(length=255), server_default="Default", nullable=False
        ),
        sa.Column("region_name", sa.String(length=255), nullable=False),
        sa.Column("auth_url", sa.String(length=2048), nullable=False),
        sa.Column("interface", sa.String(length=16), server_default="public", nullable=False),
        sa.Column("verify_tls", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING_VALIDATION", "VALID", "INVALID", "DISABLED", name="connection_status"),
            server_default="PENDING_VALIDATION",
            nullable=False,
        ),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "interface IN ('public', 'internal', 'admin')",
            name=op.f("ck_provider_connections_interface_allowed"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_provider_connections_version_positive")),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            name=op.f("fk_provider_connections_credential_id_credentials"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_provider_connections_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint(
            "provider_id",
            "project_domain_name",
            "project_name",
            "region_name",
            name="uq_provider_connections_provider_domain_project_region",
        ),
    )
    op.create_index(
        "ix_provider_connections_provider_id", "provider_connections", ["provider_id"], unique=False
    )
    op.create_index(
        "ix_provider_connections_status", "provider_connections", ["status"], unique=False
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "ACCEPTED",
                "QUEUED",
                "RUNNING",
                "WAITING_PROVIDER",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                name="operation_state",
            ),
            server_default="ACCEPTED",
            nullable=False,
        ),
        sa.Column("progress_percent", sa.SmallInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column("actor_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name=op.f("ck_operations_progress_percent_range"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_operations_version_positive")),
        sa.ForeignKeyConstraint(
            ["provider_connection_id"],
            ["provider_connections.id"],
            name=op.f("fk_operations_provider_connection_id_provider_connections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
    )
    op.create_index("ix_operations_correlation_id", "operations", ["correlation_id"], unique=False)
    op.create_index("ix_operations_created_at", "operations", ["created_at"], unique=False)
    op.create_index(
        "ix_operations_provider_connection_id",
        "operations",
        ["provider_connection_id"],
        unique=False,
    )
    op.create_index("ix_operations_state", "operations", ["state"], unique=False)
    op.create_index(
        "uq_operations_idempotency",
        "operations",
        ["provider_connection_id", "operation_type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "operation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "from_state",
            sa.Enum(
                "ACCEPTED",
                "QUEUED",
                "RUNNING",
                "WAITING_PROVIDER",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                name="operation_state",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_state",
            sa.Enum(
                "ACCEPTED",
                "QUEUED",
                "RUNNING",
                "WAITING_PROVIDER",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                name="operation_state",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_operation_events_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_operation_events_operation_id_operations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_events")),
        sa.UniqueConstraint(
            "operation_id",
            "sequence",
            name="uq_operation_events_operation_sequence",
        ),
    )
    op.create_index(
        "ix_operation_events_operation_id", "operation_events", ["operation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_operation_events_operation_id", table_name="operation_events")
    op.drop_table("operation_events")
    op.drop_index(
        "uq_operations_idempotency",
        table_name="operations",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_operations_state", table_name="operations")
    op.drop_index("ix_operations_provider_connection_id", table_name="operations")
    op.drop_index("ix_operations_created_at", table_name="operations")
    op.drop_index("ix_operations_correlation_id", table_name="operations")
    op.drop_table("operations")
    op.drop_index("ix_provider_connections_status", table_name="provider_connections")
    op.drop_index("ix_provider_connections_provider_id", table_name="provider_connections")
    op.drop_table("provider_connections")
    op.drop_index("ix_providers_status", table_name="providers")
    op.drop_index("ix_providers_name", table_name="providers")
    op.drop_table("providers")
    op.drop_index(
        "ix_outbox_messages_publish_pending",
        table_name="outbox_messages",
        postgresql_where=sa.text("publish_state = 'PENDING'"),
    )
    op.drop_index(
        "ix_outbox_messages_claim_expiry",
        table_name="outbox_messages",
        postgresql_where=sa.text("publish_state = 'CLAIMED'"),
    )
    op.drop_table("outbox_messages")
    op.drop_index("ix_inbox_messages_process_state", table_name="inbox_messages")
    op.drop_table("inbox_messages")
    op.drop_table("credentials")

    bind = op.get_bind()
    for enum_name in ENUM_TYPES:
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
