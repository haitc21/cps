"""Provider metadata ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
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
        CheckConstraint("octet_length(password_nonce) = 12", name="password_nonce_length"),
        CheckConstraint("octet_length(username_nonce) = 12", name="username_nonce_length"),
        UniqueConstraint(
            "encryption_key_version",
            "password_nonce",
            name="uq_providers_encryption_key_version_password_nonce",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="OPENSTACK",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    username_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    username_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    user_domain_name: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="Default"
    )
    credential_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ProviderStatus] = mapped_column(
        Enum(ProviderStatus, name="provider_status", native_enum=True),
        nullable=False,
        server_default=ProviderStatus.ACTIVE.name,
    )
