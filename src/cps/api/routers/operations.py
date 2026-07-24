"""Operation REST resources and validation command endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, status

from cps.api.dependencies import get_uow
from cps.api.schemas.identity import (
    IdentityLifecycleRequest,
    QuotaRequestBody,
    RoleAssignmentRequestBody,
)
from cps.api.schemas.instance import InstanceActionRequest, InstanceCreateRequest
from cps.api.schemas.inventory import InventoryRefreshRequest, InventorySyncRequest
from cps.api.schemas.operations import (
    OperationEventPage,
    OperationPage,
    OperationView,
    ValidationAccepted,
)
from cps.application.operations import OperationApplicationService
from cps.contracts.messages.identity import (
    IdentityOperation,
    IdentityResourceRequest,
    QuotaRequest,
    RoleAssignmentRequest,
)
from cps.contracts.messages.resource_operations import ScopeKind
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter(tags=["operations"])


def _service(uow: SqlAlchemyUnitOfWork) -> OperationApplicationService:
    return OperationApplicationService(uow.operations, uow.outbox, uow.inventory)


IdentityRequest = IdentityResourceRequest | RoleAssignmentRequest | QuotaRequest


async def _identity_operation(
    connection_id: uuid.UUID,
    request: IdentityRequest,
    http_request: Request,
    idempotency_key: str | None,
    uow: SqlAlchemyUnitOfWork,
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    operation = await _service(uow).create_identity_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(http_request.state.correlation_id),
        request=request,
    )
    await uow.commit()
    return ValidationAccepted(operation=operation, status_url=f"/api/v1/operations/{operation.id}")


@router.post(
    "/api/v1/provider-connections/{connection_id}/{resource_type}/{action}",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def identity_lifecycle(
    connection_id: uuid.UUID,
    resource_type: str,
    action: str,
    body: IdentityLifecycleRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if resource_type not in {"domains", "projects"} or action not in {
        "create",
        "update",
        "disable",
        "delete",
    }:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("unsupported identity resource/action")
    singular = resource_type[:-1]
    payload = body.model_dump(exclude_none=True)
    typed = IdentityResourceRequest(
        operation_id=uuid.uuid4(),
        resource_type=singular,
        operation=IdentityOperation(action),
        required_scope=ScopeKind.DOMAIN if singular == "domain" else ScopeKind.PROJECT,
        provider_connection_id=connection_id,
        **payload,
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


@router.post(
    "/api/v1/provider-connections/{connection_id}/role-assignments",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def role_assignment(
    connection_id: uuid.UUID,
    body: RoleAssignmentRequestBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    role_payload = body.model_dump(exclude={"scope_kind"})
    typed = RoleAssignmentRequest(
        operation_id=uuid.uuid4(),
        provider_connection_id=connection_id,
        required_scope=body.scope_kind,
        **role_payload,
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


@router.post(
    "/api/v1/provider-connections/{connection_id}/quotas",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def quota_operation(
    connection_id: uuid.UUID,
    body: QuotaRequestBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    typed = QuotaRequest(
        operation_id=uuid.uuid4(),
        provider_connection_id=connection_id,
        required_scope=ScopeKind.PROJECT,
        **body.model_dump(),
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


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


@router.post(
    "/api/v1/provider-connections/{connection_id}/inventory-syncs",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inventory_sync(
    connection_id: uuid.UUID,
    body: InventorySyncRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    operation = await _service(uow).create_inventory_sync(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        collections=body.collections,
        batch_size=body.batch_size,
    )
    await uow.commit()
    return ValidationAccepted(operation=operation, status_url=f"/api/v1/operations/{operation.id}")


@router.post(
    "/api/v1/provider-connections/{connection_id}/inventory-refreshes",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inventory_refresh(
    connection_id: uuid.UUID,
    body: InventoryRefreshRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    operation = await _service(uow).create_inventory_refresh(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        resource_type=body.resource_type,
        provider_resource_id=body.provider_resource_id,
    )
    await uow.commit()
    return ValidationAccepted(operation=operation, status_url=f"/api/v1/operations/{operation.id}")


@router.post(
    "/api/v1/provider-connections/{connection_id}/instances",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_instance(
    connection_id: uuid.UUID,
    body: InstanceCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    operation = await _service(uow).create_instance(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=body,
    )
    await uow.commit()
    return ValidationAccepted(operation=operation, status_url=f"/api/v1/operations/{operation.id}")


@router.post(
    "/api/v1/provider-connections/{connection_id}/instances/{instance_provider_resource_id}/{action}",
    response_model=ValidationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def instance_action(
    connection_id: uuid.UUID,
    instance_provider_resource_id: str,
    action: str,
    body: InstanceActionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> ValidationAccepted:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    try:
        action_value = body.action
        if action.lower() != action_value.value.lower():
            raise ValueError
    except ValueError as exc:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("path action does not match request action") from exc
    operation = await _service(uow).create_instance_action(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        action=action_value,
        instance_provider_resource_id=instance_provider_resource_id,
        reboot_type=body.reboot_type,
    )
    await uow.commit()
    return ValidationAccepted(operation=operation, status_url=f"/api/v1/operations/{operation.id}")


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


@router.get("/api/v1/operations/{operation_id}/audit")
async def get_operation_audit(
    operation_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> dict[str, object]:
    return await _service(uow).audit(operation_id)
