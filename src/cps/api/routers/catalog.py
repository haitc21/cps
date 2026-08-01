"""Read-only member and administrator catalog routes."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from cps.api.dependencies import get_uow
from cps.api.pagination import PaginationParams, resolve_catalog_pagination
from cps.api.response import api_success, paged_from_offset
from cps.api.schemas.catalog import (
    CatalogCompatibilityRequest,
    CatalogCompatibilityResult,
    CatalogFlavorDetail,
    CatalogFlavorSummary,
    CatalogImageDetail,
    CatalogImageSummary,
    CatalogResourceType,
    CatalogStoryResourceType,
    ImageVisibility,
    catalog_approved_from_attributes,
    compatibility_flavor_snapshot_fields,
    compatibility_image_snapshot_fields,
    enforce_catalog_response_list_bounds,
    flavor_member_visible,
    image_member_visible,
    project_flavor_detail,
    project_flavor_summary,
    project_image_detail,
    project_image_summary,
)
from cps.api.schemas.inventory import AdminCatalogCuratedView, project_admin_catalog_curated_view
from cps.application.catalog_compatibility import (
    CatalogFlavorSnapshot,
    CatalogImageSnapshot,
    CatalogUse,
    evaluate_catalog_compatibility,
)
from cps.contracts.api_response import BaseResponse, PagedData
from cps.contracts.errors import InvalidRequestError, ResourceNotFoundError
from cps.contracts.safe_metadata import validate_disk_format, validate_safe_project_id
from cps.infrastructure.db.repositories.inventory import InventoryPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.security.auth.middleware import require_admin, require_member

member_router = APIRouter(tags=["Catalog"], dependencies=[Depends(require_member)])
admin_router = APIRouter(tags=["Admin Catalog"], dependencies=[Depends(require_admin)])

_IMAGE_SIZE_BYTES_MAX = 9_223_372_036_854_775_807
_RAM_MIB_MAX = 16_777_216
_DISK_GIB_MAX = 1_048_576
_CPS_1703_CATALOG_RESOURCE_TYPES = frozenset(
    {
        CatalogResourceType.NETWORK.value,
        CatalogResourceType.VOLUME_TYPE.value,
        CatalogResourceType.AVAILABILITY_ZONE.value,
    }
)


def _reject_admin_only_member_filters(
    *,
    approved: bool | None,
    include_deleted: bool | None,
) -> None:
    if approved is not None:
        raise InvalidRequestError("approved filter is admin-only")
    if include_deleted is not None:
        raise InvalidRequestError("include_deleted is admin-only")


def _reject_member_tenant_selection_filters(
    *,
    owner_project_id: str | None,
    project_access_id: str | None,
) -> None:
    if owner_project_id is not None:
        raise InvalidRequestError("owner_project_id filter is admin-only")
    if project_access_id is not None:
        raise InvalidRequestError("project_access_id filter is admin-only")


def _validate_catalog_project_id(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_safe_project_id(value, label=label)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _admin_image_detail(row: Any) -> CatalogImageDetail:
    try:
        return project_image_detail(row)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _admin_flavor_detail(row: Any) -> CatalogFlavorDetail:
    try:
        return project_flavor_detail(row)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _member_image_summary(row: Any) -> CatalogImageSummary:
    try:
        return project_image_summary(row)
    except ValueError:
        raise ResourceNotFoundError from None


def _member_flavor_summary(row: Any) -> CatalogFlavorSummary:
    try:
        return project_flavor_summary(row)
    except ValueError:
        raise ResourceNotFoundError from None


def _validate_numeric_filter_bounds(
    *,
    size_min_bytes: int | None,
    size_max_bytes: int | None,
    min_disk_gib: int | None,
    min_ram_mib: int | None,
    min_root_disk_gib: int | None,
) -> None:
    bounds = (
        (size_min_bytes, _IMAGE_SIZE_BYTES_MAX, "size_min_bytes"),
        (size_max_bytes, _IMAGE_SIZE_BYTES_MAX, "size_max_bytes"),
        (min_disk_gib, _DISK_GIB_MAX, "min_disk_gib"),
        (min_ram_mib, _RAM_MIB_MAX, "min_ram_mib"),
        (min_root_disk_gib, _DISK_GIB_MAX, "min_root_disk_gib"),
    )
    for value, maximum, label in bounds:
        if value is not None and value > maximum:
            raise InvalidRequestError(f"{label} exceeds maximum allowed value")


def _admin_curated_resource_view(row: Any) -> AdminCatalogCuratedView:
    return project_admin_catalog_curated_view(row)


def _validate_catalog_list_filters(
    resource_type: str,
    *,
    visibility: str | None,
    owner_project_id: str | None,
    disk_format: str | None,
    size_min_bytes: int | None,
    size_max_bytes: int | None,
    min_disk_gib: int | None,
    min_ram_mib: int | None,
    min_root_disk_gib: int | None,
    project_access_id: str | None,
    is_public: bool | None,
) -> str | None:
    if resource_type in _CPS_1703_CATALOG_RESOURCE_TYPES:
        if any(
            value is not None
            for value in (
                visibility,
                owner_project_id,
                disk_format,
                size_min_bytes,
                size_max_bytes,
                min_disk_gib,
                min_ram_mib,
                is_public,
                min_root_disk_gib,
                project_access_id,
            )
        ):
            raise InvalidRequestError("filter is not valid for this catalog resource type")
        return None
    if resource_type == "image":
        if project_access_id is not None or min_root_disk_gib is not None:
            raise InvalidRequestError("filter is not valid for image catalog queries")
        if is_public is not None and visibility is not None:
            raise InvalidRequestError("Specify visibility or is_public for images, not both")
        if is_public is True:
            return ImageVisibility.PUBLIC.value
        if is_public is False:
            return ImageVisibility.PRIVATE.value
        if visibility is not None:
            try:
                return ImageVisibility(visibility).value
            except ValueError as exc:
                raise InvalidRequestError("visibility is invalid") from exc
    elif resource_type == "flavor":
        if any(
            value is not None
            for value in (
                visibility,
                owner_project_id,
                disk_format,
                size_min_bytes,
                size_max_bytes,
                min_disk_gib,
            )
        ):
            raise InvalidRequestError("filter is not valid for flavor catalog queries")
    if (
        size_min_bytes is not None
        and size_max_bytes is not None
        and size_min_bytes > size_max_bytes
    ):
        raise InvalidRequestError("size range is invalid")
    _validate_numeric_filter_bounds(
        size_min_bytes=size_min_bytes,
        size_max_bytes=size_max_bytes,
        min_disk_gib=min_disk_gib,
        min_ram_mib=min_ram_mib,
        min_root_disk_gib=min_root_disk_gib,
    )
    if disk_format is not None:
        if disk_format != disk_format.lower():
            raise InvalidRequestError("disk_format must be lowercase")
        try:
            validate_disk_format(disk_format)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
    return visibility


def _compatibility_provider_attributes(row: Any) -> dict[str, Any] | None:
    attributes = getattr(row, "provider_attributes", None)
    if attributes is None:
        return {}
    if not isinstance(attributes, dict):
        return None
    return attributes


def _snapshot_from_image(row: Any) -> CatalogImageSnapshot | None:
    if not image_member_visible(row):
        return None
    attributes = _compatibility_provider_attributes(row)
    if attributes is None:
        return None
    if not catalog_approved_from_attributes(attributes):
        return None
    try:
        container_format, member_ids = compatibility_image_snapshot_fields(
            attributes,
            min_disk_gib=row.min_disk_gib,
            min_ram_mib=row.min_ram_mib,
        )
        disk_format = validate_disk_format(row.disk_format) if row.disk_format is not None else None
    except ValueError:
        return None
    return CatalogImageSnapshot(
        provider_connection_id=row.provider_connection_id,
        provider_resource_id=row.provider_resource_id,
        lifecycle_state=row.lifecycle_state,
        provider_status=row.provider_status,
        project_provider_resource_id=row.project_provider_resource_id,
        visibility=row.visibility,
        disk_format=disk_format,
        container_format=container_format,
        min_disk_gib=row.min_disk_gib if type(row.min_disk_gib) is int else None,
        min_ram_mib=row.min_ram_mib if type(row.min_ram_mib) is int else None,
        catalog_approved=True,
        member_project_ids=member_ids,
    )


def _snapshot_from_flavor(row: Any) -> CatalogFlavorSnapshot | None:
    if not flavor_member_visible(row):
        return None
    attributes = _compatibility_provider_attributes(row)
    if attributes is None:
        return None
    if not catalog_approved_from_attributes(attributes):
        return None
    try:
        access_ids = compatibility_flavor_snapshot_fields(
            attributes,
            ram_mib=row.ram_mib,
            root_disk_gib=row.root_disk_gib,
        )
    except ValueError:
        return None
    return CatalogFlavorSnapshot(
        provider_connection_id=row.provider_connection_id,
        provider_resource_id=row.provider_resource_id,
        lifecycle_state=row.lifecycle_state,
        enabled=row.enabled if type(row.enabled) is bool else None,
        is_public=row.is_public if type(row.is_public) is bool else None,
        ram_mib=row.ram_mib if type(row.ram_mib) is int else None,
        root_disk_gib=row.root_disk_gib if type(row.root_disk_gib) is int else None,
        catalog_approved=True,
        access_project_ids=access_ids,
    )


@member_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[PagedData[CatalogImageSummary | CatalogFlavorSummary]],
)
async def list_member_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogStoryResourceType,
    pagination: PaginationParams = Depends(resolve_catalog_pagination),  # noqa: B008
    name: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(max_length=64)] = None,
    visibility: Annotated[str | None, Query(max_length=32)] = None,
    owner_project_id: Annotated[str | None, Query(max_length=255)] = None,
    disk_format: Annotated[str | None, Query(max_length=32)] = None,
    size_min_bytes: Annotated[int | None, Query(ge=0, le=_IMAGE_SIZE_BYTES_MAX)] = None,
    size_max_bytes: Annotated[int | None, Query(ge=0, le=_IMAGE_SIZE_BYTES_MAX)] = None,
    min_disk_gib: Annotated[int | None, Query(ge=0, le=_DISK_GIB_MAX)] = None,
    min_ram_mib: Annotated[int | None, Query(ge=0, le=_RAM_MIB_MAX)] = None,
    is_public: bool | None = None,
    min_root_disk_gib: Annotated[int | None, Query(ge=0, le=_DISK_GIB_MAX)] = None,
    project_access_id: Annotated[str | None, Query(max_length=255)] = None,
    approved: bool | None = None,
    include_deleted: bool | None = None,
    sort: Annotated[str, Query(pattern="^(name|created_at|updated_at)$")] = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[Any]]:
    _reject_admin_only_member_filters(approved=approved, include_deleted=include_deleted)
    _reject_member_tenant_selection_filters(
        owner_project_id=owner_project_id,
        project_access_id=project_access_id,
    )
    visibility = _validate_catalog_list_filters(
        resource_type.value,
        visibility=visibility,
        owner_project_id=owner_project_id,
        disk_format=disk_format,
        size_min_bytes=size_min_bytes,
        size_max_bytes=size_max_bytes,
        min_disk_gib=min_disk_gib,
        min_ram_mib=min_ram_mib,
        min_root_disk_gib=min_root_disk_gib,
        project_access_id=project_access_id,
        is_public=is_public,
    )
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
            name=name,
            status=status,
            approved=True,
            include_deleted=False,
            sort=sort,
            order=order,
            visibility=visibility,
            disk_format=disk_format,
            size_min_bytes=size_min_bytes,
            size_max_bytes=size_max_bytes,
            min_disk_gib=min_disk_gib,
            min_ram_mib=min_ram_mib,
            is_public=is_public if resource_type is CatalogStoryResourceType.FLAVOR else None,
            min_root_disk_gib=min_root_disk_gib,
            member_public_catalog_only=True,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if resource_type is CatalogStoryResourceType.IMAGE:
        items: list[Any] = [_member_image_summary(row) for row in rows]
    else:
        items = [_member_flavor_summary(row) for row in rows]
    enforce_catalog_response_list_bounds(items)
    return api_success(
        paged_from_offset(
            items,
            offset=pagination.offset,
            limit=pagination.limit,
            total=total,
        )
    )


@member_router.get(
    "/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
    response_model=BaseResponse[CatalogImageSummary | CatalogFlavorSummary],
)
async def get_member_catalog_resource(
    connection_id: uuid.UUID,
    resource_type: CatalogStoryResourceType,
    resource_id: uuid.UUID,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[Any]:
    try:
        row = await uow.inventory.get_catalog_resource(
            resource_type.value,
            connection_id,
            resource_id,
            approved=True,
            include_deleted=False,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    if resource_type is CatalogStoryResourceType.IMAGE:
        if not image_member_visible(row):
            raise ResourceNotFoundError
        return api_success(_member_image_summary(row))
    if not flavor_member_visible(row):
        raise ResourceNotFoundError
    return api_success(_member_flavor_summary(row))


@member_router.post(
    "/catalog/compatibility",
    response_model=BaseResponse[CatalogCompatibilityResult],
)
async def check_catalog_compatibility(
    body: CatalogCompatibilityRequest,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[CatalogCompatibilityResult]:
    image_row = None
    flavor_row = None
    if body.image_provider_resource_id:
        try:
            image_row = await uow.inventory.get_catalog_resource_by_provider_id(
                "image",
                body.provider_connection_id,
                body.image_provider_resource_id,
            )
        except InventoryPersistenceError as exc:
            raise ResourceNotFoundError from exc
    if body.flavor_provider_resource_id:
        try:
            flavor_row = await uow.inventory.get_catalog_resource_by_provider_id(
                "flavor",
                body.provider_connection_id,
                body.flavor_provider_resource_id,
            )
        except InventoryPersistenceError as exc:
            raise ResourceNotFoundError from exc
    image = None
    if image_row is not None and image_row.provider_connection_id == body.provider_connection_id:
        image = _snapshot_from_image(image_row)
    flavor = None
    if flavor_row is not None and flavor_row.provider_connection_id == body.provider_connection_id:
        flavor = _snapshot_from_flavor(flavor_row)
    result = evaluate_catalog_compatibility(
        use=CatalogUse(body.use),
        image=image,
        flavor=flavor,
        provider_connection_id=body.provider_connection_id,
        project_provider_resource_id="",
    )
    return api_success(
        CatalogCompatibilityResult(
            compatible=result.compatible,
            reason_codes=[reason.value for reason in result.reason_codes],
        )
    )


@admin_router.get(
    "/provider-connections/{connection_id}/catalog",
    response_model=BaseResponse[
        PagedData[CatalogImageDetail | CatalogFlavorDetail | AdminCatalogCuratedView]
    ],
)
async def list_admin_catalog(
    connection_id: uuid.UUID,
    resource_type: CatalogResourceType,
    pagination: PaginationParams = Depends(resolve_catalog_pagination),  # noqa: B008
    name: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(max_length=64)] = None,
    approved: bool | None = None,
    include_deleted: bool = False,
    visibility: Annotated[str | None, Query(max_length=32)] = None,
    owner_project_id: Annotated[str | None, Query(max_length=255)] = None,
    disk_format: Annotated[str | None, Query(max_length=32)] = None,
    size_min_bytes: Annotated[int | None, Query(ge=0, le=_IMAGE_SIZE_BYTES_MAX)] = None,
    size_max_bytes: Annotated[int | None, Query(ge=0, le=_IMAGE_SIZE_BYTES_MAX)] = None,
    min_disk_gib: Annotated[int | None, Query(ge=0, le=_DISK_GIB_MAX)] = None,
    min_ram_mib: Annotated[int | None, Query(ge=0, le=_RAM_MIB_MAX)] = None,
    is_public: bool | None = None,
    min_root_disk_gib: Annotated[int | None, Query(ge=0, le=_DISK_GIB_MAX)] = None,
    project_access_id: Annotated[str | None, Query(max_length=255)] = None,
    sort: Annotated[str, Query(pattern="^(name|created_at|updated_at)$")] = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[PagedData[Any]]:
    owner_project_id = _validate_catalog_project_id(
        owner_project_id,
        label="owner_project_id",
    )
    project_access_id = _validate_catalog_project_id(
        project_access_id,
        label="project_access_id",
    )
    visibility = _validate_catalog_list_filters(
        resource_type.value,
        visibility=visibility,
        owner_project_id=owner_project_id,
        disk_format=disk_format,
        size_min_bytes=size_min_bytes,
        size_max_bytes=size_max_bytes,
        min_disk_gib=min_disk_gib,
        min_ram_mib=min_ram_mib,
        min_root_disk_gib=min_root_disk_gib,
        project_access_id=project_access_id,
        is_public=is_public,
    )
    try:
        rows, total = await uow.inventory.list_catalog_resources(
            resource_type.value,
            connection_id,
            offset=pagination.offset,
            limit=pagination.limit,
            name=name,
            status=status,
            approved=approved if approved is not None else None,
            include_deleted=include_deleted,
            sort=sort,
            order=order,
            visibility=visibility,
            owner_project_id=owner_project_id,
            disk_format=disk_format,
            size_min_bytes=size_min_bytes,
            size_max_bytes=size_max_bytes,
            min_disk_gib=min_disk_gib,
            min_ram_mib=min_ram_mib,
            is_public=is_public,
            min_root_disk_gib=min_root_disk_gib,
            project_access_id=project_access_id,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if resource_type is CatalogResourceType.IMAGE:
        admin_items: list[Any] = [_admin_image_detail(row) for row in rows]
    elif resource_type is CatalogResourceType.FLAVOR:
        admin_items = [_admin_flavor_detail(row) for row in rows]
    else:
        admin_items = [_admin_curated_resource_view(row) for row in rows]
    enforce_catalog_response_list_bounds(admin_items)
    return api_success(
        paged_from_offset(
            admin_items, offset=pagination.offset, limit=pagination.limit, total=total
        )
    )


@admin_router.get(
    "/provider-connections/{connection_id}/catalog/{resource_type}/{resource_id}",
    response_model=BaseResponse[CatalogImageDetail | CatalogFlavorDetail],
)
async def get_admin_catalog_resource(
    connection_id: uuid.UUID,
    resource_type: CatalogStoryResourceType,
    resource_id: uuid.UUID,
    include_deleted: bool = False,
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),  # noqa: B008
) -> BaseResponse[Any]:
    try:
        row = await uow.inventory.get_catalog_resource(
            resource_type.value,
            connection_id,
            resource_id,
            approved=None,
            include_deleted=include_deleted,
        )
    except InventoryPersistenceError as exc:
        raise ResourceNotFoundError from exc
    if row is None:
        raise ResourceNotFoundError
    if resource_type is CatalogStoryResourceType.IMAGE:
        return api_success(_admin_image_detail(row))
    return api_success(_admin_flavor_detail(row))


# Backward-compatible alias for existing unit tests.
router = admin_router
list_catalog = list_admin_catalog
