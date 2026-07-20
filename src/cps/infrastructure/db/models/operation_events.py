"""Operation event history ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models.enums import OperationState


class OperationEvent(Base):
    __tablename__ = "operation_events"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "sequence",
            name="uq_operation_events_operation_sequence",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        Index("ix_operation_events_operation_id", "operation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[OperationState | None] = mapped_column(
        Enum(OperationState, name="operation_state", native_enum=True, create_type=False),
        nullable=True,
    )
    to_state: Mapped[OperationState | None] = mapped_column(
        Enum(OperationState, name="operation_state", native_enum=True, create_type=False),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
