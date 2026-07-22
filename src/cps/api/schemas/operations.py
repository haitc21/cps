"""Safe operation API projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from cps.infrastructure.db.models.enums import OperationState


class OperationView(BaseModel):
    id: uuid.UUID
    provider_connection_id: uuid.UUID
    operation_type: str
    state: OperationState
    progress_percent: int | None
    request_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    error_payload: dict[str, Any] | None
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    actor_context: dict[str, Any] | None
    provider_request_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class OperationPageInfo(BaseModel):
    offset: int
    limit: int
    total: int


class OperationPage(BaseModel):
    items: list[OperationView]
    page: OperationPageInfo


class OperationEventView(BaseModel):
    id: uuid.UUID
    sequence: int
    event_type: str
    from_state: OperationState | None
    to_state: OperationState | None
    message_id: uuid.UUID | None
    details: dict[str, Any]
    occurred_at: datetime


class OperationEventPage(BaseModel):
    items: list[OperationEventView]
    page: OperationPageInfo


class ValidationAccepted(BaseModel):
    operation: OperationView
    status_url: str
