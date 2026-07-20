"""Operation ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin
from cps.infrastructure.db.models.enums import OperationState


class Operation(Base, TimestampMixin, VersionMixin):
    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name="progress_percent_range",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        Index(
            "uq_operations_idempotency",
            "provider_connection_id",
            "operation_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_operations_provider_connection_id", "provider_connection_id"),
        Index("ix_operations_state", "state"),
        Index("ix_operations_created_at", "created_at"),
        Index("ix_operations_correlation_id", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[OperationState] = mapped_column(
        Enum(OperationState, name="operation_state", native_enum=True),
        nullable=False,
        server_default=OperationState.ACCEPTED.name,
    )
    progress_percent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
