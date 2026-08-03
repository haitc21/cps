"""Operation REST resources and validation command endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request, status

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.prefixes import admin_operation_status_url, member_operation_status_url
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.flavor import FlavorOperationBody
from cps.api.schemas.identity import (
    IdentityLifecycleRequest,
    QuotaRequestBody,
    RoleAssignmentRequestBody,
)
from cps.api.schemas.image import ImageOperationBody
from cps.api.schemas.instance import InstanceActionRequest, InstanceCreateRequest
from cps.api.schemas.inventory import InventoryRefreshRequest, InventorySyncRequest
from cps.api.schemas.keypair import KeypairOperationBody
from cps.api.schemas.network import NetworkOperationBody
from cps.api.schemas.operations import (
    OperationEventView,
    OperationView,
    ValidationAccepted,
)
from cps.api.schemas.volume import VolumeAttachmentOperationBody, VolumeOperationBody
from cps.api.schemas.volume_snapshot import VolumeSnapshotOperationBody
from cps.application.operations import OperationApplicationService
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.messages.flavor_operations import FlavorOperationRequest
from cps.contracts.messages.identity import (
    IdentityOperation,
    IdentityResourceRequest,
    QuotaRequest,
    RoleAssignmentRequest,
)
from cps.contracts.messages.image_operations import ImageOperationRequest
from cps.contracts.messages.keypair_operations import KeypairOperationRequest
from cps.contracts.messages.network_operations import NetworkOperationRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.volume_operations import (
    VolumeAttachmentOperationRequest,
    VolumeOperationRequest,
)
from cps.contracts.messages.volume_snapshot_operations import VolumeSnapshotOperationRequest
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin, require_member

member_router = APIRouter(tags=["Operations"], dependencies=[Depends(require_member)])
admin_router = APIRouter(tags=["Admin Operations"], dependencies=[Depends(require_admin)])


def _service(uow: SqlAlchemyUnitOfWork) -> OperationApplicationService:
    return OperationApplicationService(uow.operations, uow.outbox, uow.inventory)


IdentityRequest = IdentityResourceRequest | RoleAssignmentRequest | QuotaRequest


def _accepted(
    operation: OperationView,
    *,
    status_url: str,
) -> BaseResponse[ValidationAccepted]:
    return api_success(
        ValidationAccepted(operation=operation, status_url=status_url),
        status_code=status.HTTP_202_ACCEPTED,
    )


@member_router.post(
    "/provider-connections/{connection_id}/network-operations",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def network_operation(
    connection_id: uuid.UUID,
    body: NetworkOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = NetworkOperationRequest.model_validate(
        {"operation_id": new_uuid7(), "provider_connection_id": connection_id, **body.model_dump()}
    )
    operation = await _service(uow).create_network_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/volumes",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def volume_operation(
    connection_id: uuid.UUID,
    body: VolumeOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = VolumeOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_volume_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


@admin_router.post(
    "/provider-connections/{connection_id}/flavors",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def flavor_operation(
    connection_id: uuid.UUID,
    body: FlavorOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = FlavorOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_flavor_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@admin_router.post(
    "/provider-connections/{connection_id}/images",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def image_operation(
    connection_id: uuid.UUID,
    body: ImageOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = ImageOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_image_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/volume-snapshots",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def volume_snapshot_operation(
    connection_id: uuid.UUID,
    body: VolumeSnapshotOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = VolumeSnapshotOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_volume_snapshot_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/keypairs",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def keypair_operation(
    connection_id: uuid.UUID,
    body: KeypairOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = KeypairOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_keypair_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/volume-attachments",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def volume_attachment_operation(
    connection_id: uuid.UUID,
    body: VolumeAttachmentOperationBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    typed = VolumeAttachmentOperationRequest(
        operation_id=new_uuid7(), provider_connection_id=connection_id, **body.model_dump()
    )
    operation = await _service(uow).create_volume_attachment_operation(
        connection_id,
        idempotency_key=idempotency_key,
        correlation_id=uuid.UUID(request.state.correlation_id),
        request=typed,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


async def _identity_operation(
    connection_id: uuid.UUID,
    request: IdentityRequest,
    http_request: Request,
    idempotency_key: str | None,
    uow: SqlAlchemyUnitOfWork,
) -> BaseResponse[ValidationAccepted]:
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
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@admin_router.post(
    "/provider-connections/{connection_id}/{resource_type}/{action}",
    response_model=BaseResponse[ValidationAccepted],
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
) -> BaseResponse[ValidationAccepted]:
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
        operation_id=new_uuid7(),
        resource_type=singular,
        operation=IdentityOperation(action),
        required_scope=ScopeKind.DOMAIN if singular == "domain" else ScopeKind.PROJECT,
        provider_connection_id=connection_id,
        **payload,
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


@admin_router.post(
    "/provider-connections/{connection_id}/role-assignments",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def role_assignment(
    connection_id: uuid.UUID,
    body: RoleAssignmentRequestBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    role_payload = body.model_dump(exclude={"scope_kind"})
    typed = RoleAssignmentRequest(
        operation_id=new_uuid7(),
        provider_connection_id=connection_id,
        required_scope=body.scope_kind,
        **role_payload,
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


@admin_router.post(
    "/provider-connections/{connection_id}/quotas",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def quota_operation(
    connection_id: uuid.UUID,
    body: QuotaRequestBody,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    typed = QuotaRequest(
        operation_id=new_uuid7(),
        provider_connection_id=connection_id,
        required_scope=ScopeKind.PROJECT,
        **body.model_dump(),
    )
    return await _identity_operation(connection_id, typed, request, idempotency_key, uow)


@admin_router.post(
    "/provider-connections/{connection_id}/validate",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_connection(
    connection_id: uuid.UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
    if not idempotency_key:
        from cps.contracts.errors import InvalidRequestError

        raise InvalidRequestError("Idempotency-Key is required")
    correlation_id = uuid.UUID(request.state.correlation_id)
    operation = await _service(uow).create_validation(
        connection_id, idempotency_key=idempotency_key, correlation_id=correlation_id
    )
    await uow.commit()
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@admin_router.post(
    "/provider-connections/{connection_id}/inventory-syncs",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inventory_sync(
    connection_id: uuid.UUID,
    body: InventorySyncRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
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
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@admin_router.post(
    "/provider-connections/{connection_id}/inventory-refreshes",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inventory_refresh(
    connection_id: uuid.UUID,
    body: InventoryRefreshRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
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
    return _accepted(operation, status_url=admin_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/instances",
    response_model=BaseResponse[ValidationAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_instance(
    connection_id: uuid.UUID,
    body: InstanceCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[ValidationAccepted]:
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
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


@member_router.post(
    "/provider-connections/{connection_id}/instances/{instance_provider_resource_id}/{action}",
    response_model=BaseResponse[ValidationAccepted],
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
) -> BaseResponse[ValidationAccepted]:
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
        resize_flavor_provider_resource_id=body.resize_flavor_provider_resource_id,
        rebuild_image_provider_resource_id=body.rebuild_image_provider_resource_id,
    )
    await uow.commit()
    return _accepted(operation, status_url=member_operation_status_url(operation.id))


async def list_operations(
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    provider_connection_id: uuid.UUID | None = None,
    operation_type: str | None = None,
    state: OperationState | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[OperationView]]:
    result = await _service(uow).list(
        offset=pagination.offset,
        limit=pagination.limit,
        connection_id=provider_connection_id,
        operation_type=operation_type,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )
    return api_success(
        paged_from_offset(
            result.items,
            offset=pagination.offset,
            limit=pagination.limit,
            total=result.page.total,
        )
    )


async def get_operation(
    operation_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[OperationView]:
    return api_success(await _service(uow).get(operation_id))


async def get_operation_events(
    operation_id: uuid.UUID,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[OperationEventView]]:
    result = await _service(uow).events(
        operation_id,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return api_success(
        paged_from_offset(
            result.items,
            offset=pagination.offset,
            limit=pagination.limit,
            total=result.page.total,
        )
    )


async def get_operation_audit(
    operation_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[dict[str, object]]:
    return api_success(await _service(uow).audit(operation_id))


for _router in (member_router, admin_router):
    _router.get("/operations", response_model=BaseResponse[PagedData[OperationView]])(
        list_operations
    )
    _router.get("/operations/{operation_id}", response_model=BaseResponse[OperationView])(
        get_operation
    )
    _router.get(
        "/operations/{operation_id}/events",
        response_model=BaseResponse[PagedData[OperationEventView]],
    )(get_operation_events)
    _router.get(
        "/operations/{operation_id}/audit",
        response_model=BaseResponse[dict[str, object]],
    )(get_operation_audit)
