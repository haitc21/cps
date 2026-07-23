"""Inventory synchronization and batch persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base


class InventorySync(Base):
    __tablename__ = "inventory_syncs"
    __table_args__ = (
        CheckConstraint("sync_type IN ('FULL', 'TARGETED')", name="sync_type_allowed"),
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT')",
            name="state_allowed",
        ),
        Index("ix_inventory_syncs_connection_state", "provider_connection_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="QUEUED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_collections: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    target_resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_collections: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    skipped_collections: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    failed_collections: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class InventoryBatch(Base):
    __tablename__ = "inventory_batches"
    __table_args__ = (
        UniqueConstraint(
            "sync_id",
            "resource_type",
            "sequence",
            name="uq_inventory_batches_sync_resource_sequence",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("item_count >= 0", name="item_count_nonnegative"),
        Index("ix_inventory_batches_sync_id", "sync_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    sync_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_syncs.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_last: Mapped[bool] = mapped_column(nullable=False)
    collection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processing_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="RECEIVED"
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
