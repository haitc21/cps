"""Credential ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cps.infrastructure.db.base import Base
from cps.infrastructure.db.models._mixins import TimestampMixin, VersionMixin


class Credential(Base, TimestampMixin, VersionMixin):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("octet_length(password_nonce) = 12", name="password_nonce_length"),
        CheckConstraint(
            "octet_length(username_nonce) = 12",
            name="username_nonce_length",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "encryption_key_version",
            "password_nonce",
            name="uq_credentials_encryption_key_version_password_nonce",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    username_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    username_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    user_domain_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="Default",
    )
