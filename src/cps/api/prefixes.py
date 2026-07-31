"""Canonical public API path prefixes."""

from __future__ import annotations

import uuid

MEMBER_API_PREFIX = "/api/v1"
ADMIN_API_PREFIX = "/api/v1/admin"


def member_operation_status_url(operation_id: uuid.UUID) -> str:
    return f"{MEMBER_API_PREFIX}/operations/{operation_id}"


def admin_operation_status_url(operation_id: uuid.UUID) -> str:
    return f"{ADMIN_API_PREFIX}/operations/{operation_id}"
