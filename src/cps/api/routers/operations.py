"""Operation REST resources and validation command endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, status

from cps.api.dependencies import get_uow
from cps.api.schemas.operations import (
    OperationEventPage,
    OperationPage,
    OperationView,
    ValidationAccepted,
)
from cps.application.operations import OperationApplicationService
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(tags=["operations"])


def _service(uow: SqlAlchemyUnitOfWork) -> OperationApplicationService:
    return OperationApplicationService(uow.operations, uow.outbox)


@router.post(
    "/api/v1/provider-connections/{connection_id}/validate",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_connection(
    connection_id: uuid.UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    correlation_id = uuid.UUID(request.state.correlation_id)
    operation = await _service(uow).create_validation(
        connection_id, idempotency_key=idempotency_key, correlation_id=correlation_id
    )
    await uow.commit()
    return ValidationAccepted(
        operation=operation,
        status_url=f"/api/v1/operations/{operation.id}",
    )


@router.get("/api/v1/operations", response_model=OperationPage)
async def list_operations(
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    provider_connection_id: uuid.UUID | None = None,
    operation_type: str | None = None,
    state: OperationState | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> OperationPage:
    return await _service(uow).list(
        offset=offset,
        limit=limit,
        connection_id=provider_connection_id,
        operation_type=operation_type,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )


@router.get("/api/v1/operations/{operation_id}", response_model=OperationView)
async def get_operation(
    operation_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> OperationView:
    return await _service(uow).get(operation_id)


@router.get("/api/v1/operations/{operation_id}/events", response_model=OperationEventPage)
async def get_operation_events(
    operation_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> OperationEventPage:
    return await _service(uow).events(operation_id, offset=offset, limit=limit)
