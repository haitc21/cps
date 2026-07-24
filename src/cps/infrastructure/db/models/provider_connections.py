"""Provider connection ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus


class ProviderConnection(Base, TimestampMixin, VersionMixin):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "project_domain_name",
            "project_name",
            "region_name",
            name="uq_provider_connections_provider_domain_project_region",
        ),
        CheckConstraint(
            "interface IN ('public', 'internal', 'admin')",
            name="interface_allowed",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_provider_connections_provider_id", "provider_id"),
        Index("ix_provider_connections_status", "status"),
        Index("ix_provider_connections_scope_kind", "scope_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_kind: Mapped[ConnectionScopeKind] = mapped_column(
        Enum(ConnectionScopeKind, name="connection_scope_kind", native_enum=True),
        nullable=False,
        server_default=ConnectionScopeKind.PROJECT.name,
    )
    scope_domain_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    scope_project_provider_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    project_domain_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="Default",
    )
    region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    interface: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public")
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    ca_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, name="connection_status", native_enum=True),
        nullable=False,
        server_default=ConnectionStatus.PENDING_VALIDATION.name,
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    validation_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
