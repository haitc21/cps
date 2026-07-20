"""Inbox deduplication ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models.enums import InboxProcessState


class InboxMessage(Base):
    __tablename__ = "inbox_messages"
    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "message_id",
            name="uq_inbox_messages_consumer_message",
        ),
        Index("ix_inbox_messages_process_state", "process_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    consumer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    message_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    process_state: Mapped[InboxProcessState] = mapped_column(
        Enum(InboxProcessState, name="inbox_process_state", native_enum=True),
        nullable=False,
        server_default=InboxProcessState.RECEIVED.name,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
