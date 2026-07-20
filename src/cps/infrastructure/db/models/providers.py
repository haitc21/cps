"""Provider metadata ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Enum, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin
from cps.infrastructure.db.models.enums import ProviderStatus


class Provider(Base, TimestampMixin, VersionMixin):
    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint("provider_type = 'OPENSTACK'", name="provider_type_openstack"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_providers_status", "status"),
        Index("ix_providers_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="OPENSTACK",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProviderStatus] = mapped_column(
        Enum(ProviderStatus, name="provider_status", native_enum=True),
        nullable=False,
        server_default=ProviderStatus.ACTIVE.name,
    )
