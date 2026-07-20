"""Transactional outbox ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import VersionMixin
from cps.infrastructure.db.models.enums import OutboxPublishState

CLAIM_FIELDS_CHECK = (
    "(publish_state = 'CLAIMED' AND claimed_by IS NOT NULL "
    "AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) "
    "OR (publish_state != 'CLAIMED' AND claimed_by IS NULL "
    "AND claim_token IS NULL AND claim_expires_at IS NULL)"
)


class OutboxMessage(Base, VersionMixin):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(CLAIM_FIELDS_CHECK, name="claim_fields"),
        UniqueConstraint("message_id", name="uq_outbox_messages_message_id"),
        Index(
            "ix_outbox_messages_publish_pending",
            "publish_state",
            "next_attempt_at",
            postgresql_where=text("publish_state = 'PENDING'"),
        ),
        Index(
            "ix_outbox_messages_claim_expiry",
            "claim_expires_at",
            postgresql_where=text("publish_state = 'CLAIMED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    message_type: Mapped[str] = mapped_column(String(128), nullable=False)
    routing_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    publish_state: Mapped[OutboxPublishState] = mapped_column(
        Enum(OutboxPublishState, name="outbox_publish_state", native_enum=True),
        nullable=False,
        server_default=OutboxPublishState.PENDING.name,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
