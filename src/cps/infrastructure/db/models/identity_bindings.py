"""Explicit CMP ownership bindings for provider identity resources."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin


class IdentityBinding(Base, TimestampMixin, VersionMixin):
    """Ownership is explicit and never inferred from inventory names."""

    __tablename__ = "identity_bindings"
    __table_args__ = (
        CheckConstraint(
            "binding_kind IN ('OPENSTACK_DOMAIN', 'OPENSTACK_PROJECT')",
            name="identity_binding_kind_valid",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'READY', 'FAILED', 'DELETED')",
            name="identity_binding_status_valid",
        ),
        CheckConstraint(
            "(binding_kind = 'OPENSTACK_DOMAIN' AND workspace_id IS NULL) OR "
            "(binding_kind = 'OPENSTACK_PROJECT' AND workspace_id IS NOT NULL)",
            name="identity_binding_workspace_shape",
        ),
        CheckConstraint("version > 0", name="identity_binding_version_positive"),
        Index(
            "uq_identity_binding_domain_owner",
            "provider_id",
            "org_id",
            unique=True,
            postgresql_where=text("binding_kind = 'OPENSTACK_DOMAIN'"),
        ),
        Index(
            "uq_identity_binding_project_owner",
            "provider_id",
            "org_id",
            "workspace_id",
            unique=True,
            postgresql_where=text("binding_kind = 'OPENSTACK_PROJECT'"),
        ),
        Index(
            "uq_identity_binding_provider_resource",
            "provider_id",
            "binding_kind",
            "provider_resource_id",
            unique=True,
            postgresql_where=text("provider_resource_id IS NOT NULL"),
        ),
        Index("ix_identity_bindings_provider_id", "provider_id"),
        Index("ix_identity_bindings_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False
    )
    operation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=True
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    binding_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
