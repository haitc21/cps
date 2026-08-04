"""Read-only administrator-curated provider catalog."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.catalog import (
    CatalogFlavorSummary,
    CatalogImageSummary,
    CatalogMemberResourceSummary,
    CatalogMemberResourceType,
    CatalogResourceType,
)
from cps.api.schemas.inventory import InventoryResourceView
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import ResourceNotFoundError
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin, require_member

admin_router = APIRouter(tags=["Admin Catalog"], dependencies=[Depends(require_admin)])
member_router = APIRouter(tags=["Catalog"], dependencies=[Depends(require_member)])
# Compatibility name for callers that still import the original admin router.
router = admin_router

_SENSITIVE_METADATA_PARTS = (
    "password",
    "token",
    "authorization",
    "private_key",
    "user_data",
    "signed_url",
)
_MAX_METADATA_DEPTH = 4
_MAX_METADATA_ENTRIES = 128
_MAX_METADATA_STRING_LENGTH = 4096


def _safe_catalog_metadata(value: Any, *, depth: int = 0) -> dict[str, Any]:
    """Return bounded catalog metadata without secret-like keys."""
    if not isinstance(value, Mapping) or depth > _MAX_METADATA_DEPTH:
        return {}
    result: dict[str, Any] = {}
    for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
        key = str(raw_key)
        lowered = key.lower()
        if not key or any(part in lowered for part in _SENSITIVE_METADATA_PARTS):
            continue
        if isinstance(raw_value, str):
            if len(raw_value) <= _MAX_METADATA_STRING_LENGTH:
                result[key] = raw_value
        elif raw_value is None or isinstance(raw_value, bool | int | float):
            result[key] = raw_value
        elif isinstance(raw_value, Mapping):
            result[key] = _safe_catalog_metadata(raw_value, depth=depth + 1)
        elif isinstance(raw_value, list | tuple):
            result[key] = [
                item
                for item in raw_value[:_MAX_METADATA_ENTRIES]
                if isinstance(item, str | int | float | bool)
            ]
        if len(result) >= _MAX_METADATA_ENTRIES:
            break
    return result


@admin_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[PagedData[InventoryResourceView]],
)
async def list_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogResourceType,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    name: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(max_length=64)] = None,
    visibility: Annotated[str | None, Query(pattern="^(public|private|shared|community)$")] = None,
    sort: Annotated[str, Query(pattern="^(name|created_at|updated_at)$")] = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[InventoryResourceView]]:
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
            name=name,
            status=status,
            visibility=visibility,
            sort=sort,
            order=order,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return api_success(
        paged_from_offset(
            [_admin_view(row) for row in rows],
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


def _member_view(
    resource_type: CatalogMemberResourceType, row: object
) -> CatalogMemberResourceSummary:
    values = vars(row)
    attributes = _safe_catalog_metadata(values.get("provider_attributes", {}))
    approved = attributes.get("catalog_approved") is True if isinstance(attributes, dict) else False
    common = {
        "id": values.get("id"),
        "provider_connection_id": values.get("provider_connection_id"),
        "provider_resource_id": values.get("provider_resource_id"),
        "name": values.get("name"),
        "provider_status": values.get("provider_status"),
        "catalog_approved": approved,
    }
    if resource_type is CatalogMemberResourceType.IMAGE:
        status = str(values.get("provider_status") or "").lower()
        protected = attributes.get("is_protected")
        allowed_actions: list[str] = []
        if status == "active":
            allowed_actions.append("deactivate")
        elif status == "deactivated":
            allowed_actions.append("reactivate")
        if protected is False:
            allowed_actions.append("delete")
        return CatalogImageSummary.model_validate(
            {
                **common,
                "visibility": values.get("visibility"),
                "is_public": attributes.get("is_public"),
                "size_bytes": values.get("size_bytes"),
                "min_disk_gib": values.get("min_disk_gib"),
                "min_ram_mib": values.get("min_ram_mib"),
                "disk_format": values.get("disk_format"),
                "checksum": values.get("checksum"),
                "is_protected": protected,
                "tags": attributes.get("tags", []),
                "properties": attributes.get("properties", {}),
                "allowed_actions": allowed_actions,
                "capabilities": {
                    "deactivate": status == "active",
                    "reactivate": status == "deactivated",
                    "delete": protected is False,
                },
            }
        )
    status = str(values.get("provider_status") or "").lower()
    return CatalogFlavorSummary.model_validate(
        {
            **common,
            "vcpus": values.get("vcpus"),
            "ram_mib": values.get("ram_mib"),
            "root_disk_gib": values.get("root_disk_gib"),
            "ephemeral_disk_gib": values.get("ephemeral_disk_gib"),
            "swap_mib": values.get("swap_mib"),
            "is_public": values.get("is_public"),
            "enabled": values.get("enabled"),
            "extra_specs": attributes.get("extra_specs", {}),
            "access_project_ids": attributes.get("access_project_ids", []),
            "allowed_actions": (
                ["delete", "update-access", "update-extra-specs"] if status == "active" else []
            ),
            "capabilities": {
                "delete": status == "active",
                "update-access": status == "active",
                "update-extra-specs": status == "active",
            },
        }
    )


def _admin_view(row: object) -> InventoryResourceView:
    """Expose typed admin inventory fields without raw provider metadata."""
    view = InventoryResourceView.model_validate(row, from_attributes=True)
    return view.model_copy(update={"provider_attributes": {}})


@member_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[PagedData[CatalogMemberResourceSummary]],
)
async def list_member_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogMemberResourceType,
    pagination: PaginationParams = Depends(resolve_pagination),  # noqa: B008
    name: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(max_length=64)] = None,
    visibility: Annotated[str | None, Query(pattern="^(public|private|shared|community)$")] = None,
    sort: Annotated[str, Query(pattern="^(name|created_at|updated_at)$")] = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[CatalogMemberResourceSummary]]:
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
            name=name,
            status=status,
            visibility=visibility,
            sort=sort,
            order=order,
            member_scope=True,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    return api_success(
        paged_from_offset(
            [_member_view(resource_type, row) for row in rows],
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


@member_router.get(
    "/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
    response_model=BaseResponse[CatalogMemberResourceSummary],
)
async def get_member_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogMemberResourceType,
    resource_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[CatalogMemberResourceSummary]:
    try:
        row = await uow.inventory.get_catalog_resource(
            resource_type.value, connection_id, resource_id, member_scope=True
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    return api_success(_member_view(resource_type, row))
