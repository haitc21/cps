"""Idempotent operation creation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from cps.domain.operations.errors import IdempotencyConflictError, OperationPersistenceError
from cps.domain.operations.idempotency import canonical_fingerprint
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.repositories.operations import IdempotencyScopeConflictError

if TYPE_CHECKING:
    from cps.infrastructure.db.repositories.operations import OperationRepository


async def create_operation_idempotent(
    repository: OperationRepository,
    *,
    provider_connection_id: uuid.UUID,
    operation_type: str,
    request_payload: dict[str, Any],
    correlation_id: uuid.UUID,
    idempotency_key: str | None = None,
    causation_id: uuid.UUID | None = None,
    actor_context: dict[str, Any] | None = None,
    timeout_at: datetime | None = None,
) -> Operation:
    """Create an operation or return the existing row for the same idempotency scope."""
    fingerprint = canonical_fingerprint(request_payload)

    if idempotency_key is not None:
        existing = await repository.get_by_idempotency_scope(
            provider_connection_id=provider_connection_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            _ensure_same_fingerprint(existing, fingerprint)
            return existing

    try:
        return await repository.insert_operation(
            operation_id=new_uuid7(),
            provider_connection_id=provider_connection_id,
            operation_type=operation_type,
            request_payload=request_payload,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            causation_id=causation_id,
            actor_context=actor_context,
            timeout_at=timeout_at,
        )
    except IdempotencyScopeConflictError:
        if idempotency_key is None:
            msg = "operation persistence failed"
            raise OperationPersistenceError(msg) from None
        existing = await repository.get_by_idempotency_scope(
            provider_connection_id=provider_connection_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            msg = "operation persistence failed"
            raise OperationPersistenceError(msg) from None
        _ensure_same_fingerprint(existing, fingerprint)
        return existing


def _ensure_same_fingerprint(existing: Operation, fingerprint: str) -> None:
    if existing.request_fingerprint != fingerprint:
        msg = "idempotency key reused with different request payload"
        raise IdempotencyConflictError(msg)
