"""Inventory sync and batch persistence with idempotent ingestion."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cps.contracts.messages.inventory import (
    OWNERSHIP_CONFLICT_MESSAGE,
    InventoryBatchPayload,
    InventoryCollectionStatus,
    OwnershipConflictError,
    canonicalize_inventory_item,
    resolve_owner_project_provider_resource_id,
)
from cps.contracts.safe_metadata import validate_volume_attachment_resource
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.inventory import (
    AvailabilityZone,
    Flavor,
    FloatingIP,
    IdentityDomain,
    Image,
    Instance,
    InstancePort,
    InstanceVolume,
    Keypair,
    Network,
    Port,
    Project,
    Quota,
    Region,
    RoleAssignment,
    Router,
    SecurityGroup,
    SecurityGroupRule,
    Subnet,
    Volume,
    VolumeSnapshot,
    VolumeType,
)
from cps.infrastructure.db.models.inventory_sync import InventoryBatch, InventorySync
from cps.infrastructure.db.models.provider_connections import ProviderConnection

RESOURCE_MODELS: dict[str, Any] = {
    "domain": IdentityDomain,
    "region": Region,
    "project": Project,
    "role-assignment": RoleAssignment,
    "quota": Quota,
    "flavor": Flavor,
    "availability-zone": AvailabilityZone,
    "image": Image,
    "instance": Instance,
    "network": Network,
    "subnet": Subnet,
    "port": Port,
    "router": Router,
    "security-group": SecurityGroup,
    "security-group-rule": SecurityGroupRule,
    "floating-ip": FloatingIP,
    "volume": Volume,
    "volume-type": VolumeType,
    "volume-snapshot": VolumeSnapshot,
    "keypair": Keypair,
}
RESOURCE_ALIASES = {f"{key}s": key for key in RESOURCE_MODELS}
RESOURCE_ALIASES["snapshot"] = "volume-snapshot"
RESOURCE_ALIASES.update({"identity-domains": "domain", "identity_domain": "domain"})
RESOURCE_ALIASES.update(
    {"role-assignments": "role-assignment", "role_assignment": "role-assignment", "quotas": "quota"}
)
RESOURCE_ALIASES["indices"] = "instance"


class InventoryPersistenceError(RuntimeError):
    """Stable error for invalid or conflicting inventory persistence."""


class InventoryBatchConflictError(InventoryPersistenceError):
    """A replayed batch identity has different immutable content."""


class InventorySyncIncompleteError(InventoryPersistenceError):
    """A sync cannot finalize because collection integrity is incomplete."""


_CATALOG_APPROVED_MARKER = {"catalog_approved": True}


@dataclass(frozen=True)
class CatalogResourceQuery:
    name: str | None = None
    status: str | None = None
    approved: bool | None = True
    include_deleted: bool = False
    sort: str = "name"
    order: str = "asc"
    visibility: str | None = None
    owner_project_id: str | None = None
    disk_format: str | None = None
    size_min_bytes: int | None = None
    size_max_bytes: int | None = None
    min_disk_gib: int | None = None
    min_ram_mib: int | None = None
    is_public: bool | None = None
    min_root_disk_gib: int | None = None
    project_access_id: str | None = None
    member_project_scope: str | None = None
    member_live_only: bool = False
    member_public_catalog_only: bool = False


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_provider_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _project_ownership_conflict_update(model: Any, statement: Any) -> dict[str, Any]:
    """Preserve project linkage when refresh omits owner; allow safe resolved transitions."""
    excluded_project_id = statement.excluded.project_id
    excluded_owner = statement.excluded.project_provider_resource_id
    return {
        "project_provider_resource_id": sa.case(
            (excluded_owner.is_(None), model.project_provider_resource_id),
            (excluded_project_id.isnot(None), excluded_owner),
            (
                excluded_owner == model.project_provider_resource_id,
                model.project_provider_resource_id,
            ),
            else_=excluded_owner,
        ),
        "project_id": sa.case(
            (excluded_owner.is_(None), model.project_id),
            (excluded_project_id.isnot(None), excluded_project_id),
            (excluded_owner == model.project_provider_resource_id, model.project_id),
            else_=sa.null(),
        ),
    }


def _member_public_catalog_clause(model: Any, resource_type: str) -> Any:
    if resource_type == "image":
        return sa.and_(
            model.lifecycle_state == "ACTIVE",
            func.lower(model.provider_status) == "active",
            model.visibility.in_(("public", "community")),
        )
    if resource_type == "flavor":
        return sa.and_(
            model.lifecycle_state == "ACTIVE",
            or_(model.enabled.is_(True), model.enabled.is_(None)),
            model.is_public.is_(True),
        )
    msg = "member catalog filtering requires image or flavor"
    raise InventoryPersistenceError(msg)


def _member_scope_clause(model: Any, resource_type: str, project_scope: str) -> Any:
    if resource_type == "image":
        shared = sa.and_(
            model.visibility == "shared",
            model.provider_attributes["member_project_ids"].contains([project_scope]),
        )
        private = sa.and_(
            model.visibility == "private",
            model.project_provider_resource_id == project_scope,
        )
        public = model.visibility.in_(("public", "community"))
        return sa.and_(
            model.lifecycle_state == "ACTIVE",
            func.lower(model.provider_status) == "active",
            or_(public, private, shared),
        )
    if resource_type == "flavor":
        private = model.provider_attributes["access_project_ids"].contains([project_scope])
        public = model.is_public.is_(True)
        return sa.and_(
            model.lifecycle_state == "ACTIVE",
            or_(model.enabled.is_(True), model.enabled.is_(None)),
            or_(public, private),
        )
    msg = "member scope filtering requires image or flavor"
    raise InventoryPersistenceError(msg)


class InventoryRepository:
    """Repository whose caller owns the transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_project_id(
        self, provider_connection_id: uuid.UUID, provider_project_id: str | None
    ) -> uuid.UUID | None:
        if not provider_project_id:
            return None
        provider_id = await self._session.scalar(
            select(ProviderConnection.provider_id).where(
                ProviderConnection.id == provider_connection_id
            )
        )
        if provider_id is None:
            return None
        project_id = await self._session.scalar(
            select(Project.id).where(
                Project.provider_id == provider_id,
                Project.provider_resource_id == provider_project_id,
                Project.lifecycle_state != "DELETED",
            )
        )
        return project_id

    async def create_sync(
        self,
        *,
        sync_id: uuid.UUID,
        operation_id: uuid.UUID,
        provider_connection_id: uuid.UUID,
        sync_type: str,
        expected_collections: list[str],
        target_resource_type: str | None = None,
        target_provider_resource_id: str | None = None,
    ) -> InventorySync:
        sync = InventorySync(
            id=sync_id,
            operation_id=operation_id,
            provider_connection_id=provider_connection_id,
            sync_type=sync_type,
            expected_collections=copy.deepcopy(expected_collections),
            target_resource_type=target_resource_type,
            target_provider_resource_id=target_provider_resource_id,
        )
        self._session.add(sync)
        await self._session.flush()
        return sync

    async def get_sync(self, sync_id: uuid.UUID) -> InventorySync | None:
        result = await self._session.execute(
            select(InventorySync).where(InventorySync.id == sync_id)
        )
        return result.scalar_one_or_none()

    async def get_resource(self, resource_type: str, resource_id: uuid.UUID) -> Any | None:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        result = await self._session.execute(select(model).where(model.id == resource_id))
        return result.scalar_one_or_none()

    async def resource_belongs_to_connection(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        provider_resource_id: str,
    ) -> bool:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        result = await self._session.execute(
            select(model.id).where(
                model.provider_connection_id == provider_connection_id,
                model.provider_resource_id == provider_resource_id,
                model.lifecycle_state != "DELETED",
            )
        )
        return result.scalar_one_or_none() is not None

    async def resource_name_belongs_to_connection(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        name: str,
    ) -> bool:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        result = await self._session.execute(
            select(model.id).where(
                model.provider_connection_id == provider_connection_id,
                model.name == name,
                model.lifecycle_state != "DELETED",
            )
        )
        return result.scalar_one_or_none() is not None

    async def live_flavor_name_exists_case_insensitive(
        self, provider_connection_id: uuid.UUID, name: str
    ) -> bool:
        result = await self._session.execute(
            select(Flavor.id).where(
                Flavor.provider_connection_id == provider_connection_id,
                func.lower(Flavor.name) == name.casefold(),
                Flavor.lifecycle_state != "DELETED",
            )
        )
        return result.scalar_one_or_none() is not None

    async def project_provider_ids_belong_to_provider(
        self, provider_id: uuid.UUID, provider_resource_ids: list[str]
    ) -> bool:
        """Resolve live Keystone project identities across a provider aggregate."""
        if not provider_resource_ids:
            return True
        count = await self._session.scalar(
            select(func.count(func.distinct(Project.provider_resource_id))).where(
                Project.provider_id == provider_id,
                Project.provider_resource_id.in_(provider_resource_ids),
                Project.lifecycle_state != "DELETED",
            )
        )
        return count == len(provider_resource_ids)

    async def flavor_mutation_state(
        self, provider_connection_id: uuid.UUID, provider_resource_id: str
    ) -> tuple[bool, bool] | None:
        """Return ``(is_public, catalog_approved)`` for a live flavor."""
        row = await self._session.execute(
            select(Flavor.is_public, Flavor.provider_attributes).where(
                Flavor.provider_connection_id == provider_connection_id,
                Flavor.provider_resource_id == provider_resource_id,
                Flavor.lifecycle_state == "ACTIVE",
                Flavor.enabled.is_not(False),
            )
        )
        value = row.one_or_none()
        if value is None:
            return None
        return value.is_public is True, value.provider_attributes.get("catalog_approved") is True

    async def flavor_is_used_on_provider(
        self, provider_id: uuid.UUID, provider_resource_id: str
    ) -> bool:
        """Fail closed when any live instance on this provider references a flavor."""
        found = await self._session.scalar(
            select(Instance.id)
            .join(
                ProviderConnection,
                ProviderConnection.id == Instance.provider_connection_id,
            )
            .where(
                ProviderConnection.provider_id == provider_id,
                Instance.flavor_provider_resource_id == provider_resource_id,
                Instance.lifecycle_state != "DELETED",
            )
            .limit(1)
        )
        return found is not None

    async def catalog_resource_is_approved(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        provider_resource_id: str,
    ) -> bool:
        """Return true only for a live resource explicitly approved by admin."""
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        result = await self._session.execute(
            select(model.id).where(
                model.provider_connection_id == provider_connection_id,
                model.provider_resource_id == provider_resource_id,
                model.lifecycle_state != "DELETED",
                model.provider_attributes.contains(_CATALOG_APPROVED_MARKER),
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_catalog_resources(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
        name: str | None = None,
        status: str | None = None,
        approved: bool | None = True,
        include_deleted: bool = False,
        sort: str = "name",
        order: str = "asc",
        visibility: str | None = None,
        owner_project_id: str | None = None,
        disk_format: str | None = None,
        size_min_bytes: int | None = None,
        size_max_bytes: int | None = None,
        min_disk_gib: int | None = None,
        min_ram_mib: int | None = None,
        is_public: bool | None = None,
        min_root_disk_gib: int | None = None,
        project_access_id: str | None = None,
        member_project_scope: str | None = None,
        member_live_only: bool = False,
        member_public_catalog_only: bool = False,
    ) -> tuple[list[Any], int]:
        query = CatalogResourceQuery(
            name=name,
            status=status,
            approved=approved,
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
            member_project_scope=member_project_scope,
            member_live_only=member_live_only,
            member_public_catalog_only=member_public_catalog_only,
        )
        return await self._list_catalog_resources(
            resource_type,
            provider_connection_id,
            query=query,
            offset=offset,
            limit=limit,
        )

    async def get_catalog_resource(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        resource_id: uuid.UUID,
        *,
        approved: bool | None = True,
        include_deleted: bool = False,
    ) -> Any | None:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        filters = [
            model.id == resource_id,
            model.provider_connection_id == provider_connection_id,
        ]
        if not include_deleted:
            filters.append(model.lifecycle_state != "DELETED")
        if approved is True:
            filters.append(model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        elif approved is False:
            filters.append(~model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        result = await self._session.execute(select(model).where(*filters))
        return result.scalar_one_or_none()

    async def get_catalog_resource_by_provider_id(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        provider_resource_id: str,
        *,
        approved: bool | None = None,
        include_deleted: bool = False,
    ) -> Any | None:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        filters = [
            model.provider_connection_id == provider_connection_id,
            model.provider_resource_id == provider_resource_id,
        ]
        if not include_deleted:
            filters.append(model.lifecycle_state != "DELETED")
        if approved is True:
            filters.append(model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        elif approved is False:
            filters.append(~model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        result = await self._session.execute(select(model).where(*filters))
        return result.scalar_one_or_none()

    async def _list_catalog_resources(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        *,
        query: CatalogResourceQuery,
        offset: int,
        limit: int,
    ) -> tuple[list[Any], int]:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        filters = [model.provider_connection_id == provider_connection_id]
        if not query.include_deleted:
            filters.append(model.lifecycle_state != "DELETED")
        if query.approved is True:
            filters.append(model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        elif query.approved is False:
            filters.append(~model.provider_attributes.contains(_CATALOG_APPROVED_MARKER))
        if query.name is not None:
            escaped = _escape_like_pattern(query.name)
            filters.append(model.name.ilike(f"%{escaped}%", escape="\\"))
        if query.status is not None:
            filters.append(func.lower(model.provider_status) == query.status.lower())
        if resource_type == "image":
            if query.visibility is not None:
                filters.append(model.visibility == query.visibility)
            if query.owner_project_id is not None:
                filters.append(model.project_provider_resource_id == query.owner_project_id)
            if query.disk_format is not None:
                filters.append(model.disk_format == query.disk_format)
            if query.size_min_bytes is not None:
                filters.append(model.size_bytes >= query.size_min_bytes)
            if query.size_max_bytes is not None:
                filters.append(model.size_bytes <= query.size_max_bytes)
            if query.min_disk_gib is not None:
                filters.append(model.min_disk_gib >= query.min_disk_gib)
            if query.min_ram_mib is not None:
                filters.append(model.min_ram_mib >= query.min_ram_mib)
        if resource_type == "flavor":
            if query.is_public is not None:
                filters.append(model.is_public.is_(query.is_public))
            if query.min_root_disk_gib is not None:
                filters.append(model.root_disk_gib >= query.min_root_disk_gib)
            if query.min_ram_mib is not None:
                filters.append(model.ram_mib >= query.min_ram_mib)
            if query.project_access_id is not None:
                filters.append(
                    model.provider_attributes["access_project_ids"].contains(
                        [query.project_access_id]
                    )
                )
        if query.member_public_catalog_only:
            filters.append(_member_public_catalog_clause(model, resource_type))
        elif query.member_live_only and query.member_project_scope is not None:
            filters.append(
                _member_scope_clause(model, resource_type, query.member_project_scope)
            )
        total = int(
            (
                await self._session.execute(select(func.count()).select_from(model).where(*filters))
            ).scalar_one()
        )
        column = {
            "name": model.name,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }.get(query.sort, model.name)
        direction = column.asc() if query.order == "asc" else column.desc()
        tie = model.id.asc() if query.order == "asc" else model.id.desc()
        result = await self._session.execute(
            select(model)
            .where(*filters)
            .order_by(direction, tie)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total

    async def mark_resource_deleted(
        self,
        resource_type: str,
        provider_connection_id: uuid.UUID,
        provider_resource_id: str,
    ) -> bool:
        model = RESOURCE_MODELS.get(RESOURCE_ALIASES.get(resource_type, resource_type))
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        result = await self._session.execute(
            update(model)
            .where(
                model.provider_connection_id == provider_connection_id,
                model.provider_resource_id == provider_resource_id,
            )
            .values(lifecycle_state="DELETED", deleted_at=datetime.now(UTC))
        )
        return bool(getattr(result, "rowcount", 0))

    async def persist_instance_result(
        self,
        *,
        provider_connection_id: uuid.UUID,
        sync_id: uuid.UUID | None,
        instance: dict[str, Any],
        ports: list[dict[str, Any]] | None = None,
        volumes: list[dict[str, Any]] | None = None,
    ) -> Any:
        provider_resource_id = instance.get("provider_resource_id")
        name = instance.get("name")
        if not isinstance(provider_resource_id, str) or not isinstance(name, str):
            raise InventoryPersistenceError("instance result identity is invalid")
        await self._upsert_resource(
            model=Instance,
            provider_connection_id=provider_connection_id,
            sync_id=sync_id or uuid.uuid4(),
            item={
                "provider_resource_id": provider_resource_id,
                "name": name,
                "provider_status": instance.get("provider_status"),
                "lifecycle_state": instance.get("lifecycle_state", "ACTIVE"),
                "attributes": instance.get("attributes", {}),
                "provider_created_at": instance.get("provider_created_at"),
                "provider_updated_at": instance.get("provider_updated_at"),
            },
        )
        result = await self._session.execute(
            select(Instance).where(
                Instance.provider_connection_id == provider_connection_id,
                Instance.provider_resource_id == provider_resource_id,
            )
        )
        instance_row = result.scalar_one()
        for port_item in ports or []:
            await self._upsert_resource(
                model=Port,
                provider_connection_id=provider_connection_id,
                sync_id=sync_id or uuid.uuid4(),
                item=port_item,
            )
            port_result = await self._session.execute(
                select(Port).where(
                    Port.provider_connection_id == provider_connection_id,
                    Port.provider_resource_id == port_item["provider_resource_id"],
                )
            )
            port_row = port_result.scalar_one()
            await self._session.merge(
                InstancePort(
                    instance_id=instance_row.id,
                    port_id=port_row.id,
                    provider_port_resource_id=port_row.provider_resource_id,
                    device=port_item.get("attributes", {}).get("device_id"),
                )
            )
        for volume_item in volumes or []:
            await self._upsert_resource(
                model=Volume,
                provider_connection_id=provider_connection_id,
                sync_id=sync_id or uuid.uuid4(),
                item=volume_item,
            )
            volume_result = await self._session.execute(
                select(Volume).where(
                    Volume.provider_connection_id == provider_connection_id,
                    Volume.provider_resource_id == volume_item["provider_resource_id"],
                )
            )
            volume_row = volume_result.scalar_one()
            attributes = volume_item.get("attributes", {})
            await self._session.merge(
                InstanceVolume(
                    instance_id=instance_row.id,
                    volume_id=volume_row.id,
                    provider_volume_resource_id=volume_row.provider_resource_id,
                    device=attributes.get("device"),
                    boot_index=attributes.get("boot_index"),
                    delete_on_termination=attributes.get("delete_on_termination"),
                )
            )
        return instance_row

    async def persist_snapshot_result(
        self,
        *,
        provider_connection_id: uuid.UUID,
        sync_id: uuid.UUID | None,
        snapshot: dict[str, Any],
    ) -> VolumeSnapshot:
        provider_resource_id = snapshot.get("provider_resource_id")
        name = snapshot.get("name")
        if not isinstance(provider_resource_id, str) or not isinstance(name, str):
            raise InventoryPersistenceError("snapshot result identity is invalid")
        attributes = snapshot.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        metadata = snapshot.get("metadata")
        if not isinstance(metadata, dict):
            raw_metadata = attributes.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        await self._upsert_resource(
            model=VolumeSnapshot,
            provider_connection_id=provider_connection_id,
            sync_id=sync_id or uuid.uuid4(),
            item={
                "provider_resource_id": provider_resource_id,
                "name": name,
                "provider_status": snapshot.get("provider_status"),
                "lifecycle_state": snapshot.get("lifecycle_state", "ACTIVE"),
                "project_provider_resource_id": snapshot.get("project_provider_resource_id"),
                "volume_provider_resource_id": snapshot.get("volume_provider_resource_id"),
                "snapshot_size_gib": snapshot.get("snapshot_size_gib", snapshot.get("size")),
                "metadata": metadata,
                "attributes": attributes,
                "provider_created_at": snapshot.get("provider_created_at"),
                "provider_updated_at": snapshot.get("provider_updated_at"),
            },
        )
        result = await self._session.execute(
            select(VolumeSnapshot).where(
                VolumeSnapshot.provider_connection_id == provider_connection_id,
                VolumeSnapshot.provider_resource_id == provider_resource_id,
            )
        )
        return result.scalar_one()

    async def persist_flavor_result(
        self,
        *,
        provider_connection_id: uuid.UUID,
        flavor: dict[str, Any],
    ) -> Flavor:
        """Upsert one validated, complete flavor operation snapshot."""
        from cps.contracts.messages.flavor_operations import FlavorSnapshot

        snapshot = FlavorSnapshot.model_validate(flavor)
        existing = await self._session.scalar(
            select(Flavor).where(
                Flavor.provider_connection_id == provider_connection_id,
                Flavor.provider_resource_id == snapshot.provider_resource_id,
            )
        )
        prior_attributes = existing.provider_attributes if existing is not None else {}
        attributes = {
            "catalog_approved": prior_attributes.get("catalog_approved", False),
            "access_project_ids": snapshot.access_project_ids,
            "extra_specs": snapshot.extra_specs,
        }
        await self._upsert_resource(
            model=Flavor,
            provider_connection_id=provider_connection_id,
            sync_id=uuid.uuid4(),
            item={
                "provider_resource_id": snapshot.provider_resource_id,
                "name": snapshot.name,
                "lifecycle_state": "ACTIVE",
                "vcpus": snapshot.vcpus,
                "ram_mib": snapshot.ram_mib,
                "root_disk_gib": snapshot.root_disk_gib,
                "ephemeral_disk_gib": snapshot.ephemeral_disk_gib,
                "swap_mib": snapshot.swap_mib,
                "is_public": snapshot.is_public,
                "enabled": True,
                "attributes": attributes,
            },
        )
        result = await self._session.execute(
            select(Flavor).where(
                Flavor.provider_connection_id == provider_connection_id,
                Flavor.provider_resource_id == snapshot.provider_resource_id,
            )
        )
        return result.scalar_one()

    async def apply_volume_attachment_result(
        self,
        *,
        provider_connection_id: uuid.UUID,
        operation: str,
        instance_provider_resource_id: str,
        volume_provider_resource_id: str,
        resource: dict[str, Any] | None = None,
    ) -> bool:
        """Project a terminal attachment event onto tracked inventory rows.

        Provider-created resources may arrive before a full inventory sync. In
        that case there is nothing safe to relate yet; the next refresh owns
        reconciliation and this method deliberately returns ``False``.
        """
        instance = await self._session.scalar(
            select(Instance).where(
                Instance.provider_connection_id == provider_connection_id,
                Instance.provider_resource_id == instance_provider_resource_id,
                Instance.lifecycle_state != "DELETED",
            )
        )
        volume = await self._session.scalar(
            select(Volume).where(
                Volume.provider_connection_id == provider_connection_id,
                Volume.provider_resource_id == volume_provider_resource_id,
                Volume.lifecycle_state != "DELETED",
            )
        )
        if instance is None or volume is None:
            return False
        try:
            validated_resource = validate_volume_attachment_resource(resource)
        except ValueError as exc:
            raise InventoryPersistenceError(
                "volume attachment resource failed canonical validation"
            ) from exc
        relation = {
            "instance_id": instance.id,
            "volume_id": volume.id,
            "provider_volume_resource_id": volume.provider_resource_id,
            "device": validated_resource.get("device"),
            "boot_index": validated_resource.get("boot_index"),
            "delete_on_termination": validated_resource.get("delete_on_termination"),
        }
        if operation == "attach":
            await self._session.merge(InstanceVolume(**relation))
        elif operation == "detach":
            await self._session.execute(
                delete(InstanceVolume).where(
                    InstanceVolume.instance_id == instance.id,
                    InstanceVolume.volume_id == volume.id,
                )
            )
        else:
            raise InventoryPersistenceError("unsupported volume attachment operation")
        return True

    async def list_resources(
        self,
        resource_type: str,
        *,
        offset: int,
        limit: int,
        provider_connection_id: uuid.UUID | None = None,
        provider_resource_id: str | None = None,
        project_provider_resource_id: str | None = None,
        name: str | None = None,
        include_deleted: bool = False,
        sort: str = "created_at",
        order: str = "asc",
    ) -> tuple[list[Any], int]:
        resource_type = RESOURCE_ALIASES.get(resource_type, resource_type)
        model = RESOURCE_MODELS.get(resource_type)
        if model is None:
            raise InventoryPersistenceError("unsupported inventory resource type")
        filters = []
        if provider_connection_id is not None:
            filters.append(model.provider_connection_id == provider_connection_id)
        if provider_resource_id is not None:
            filters.append(model.provider_resource_id == provider_resource_id)
        if project_provider_resource_id is not None and hasattr(
            model, "project_provider_resource_id"
        ):
            filters.append(model.project_provider_resource_id == project_provider_resource_id)
        if name is not None:
            filters.append(model.name.ilike(f"%{name}%"))
        if not include_deleted:
            filters.append(model.lifecycle_state != "DELETED")
        total = int(
            (
                await self._session.execute(select(func.count()).select_from(model).where(*filters))
            ).scalar_one()
        )
        column = {
            "name": model.name,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }.get(sort, model.created_at)
        direction = column.asc() if order == "asc" else column.desc()
        tie = model.id.asc() if order == "asc" else model.id.desc()
        result = await self._session.execute(
            select(model).where(*filters).order_by(direction, tie).offset(offset).limit(limit)
        )
        return list(result.scalars()), total

    async def persist_batch(
        self,
        *,
        sync: InventorySync,
        message_id: uuid.UUID,
        provider_connection_id: uuid.UUID,
        batch: InventoryBatchPayload,
    ) -> InventoryBatch:
        if batch.resource_type.value not in RESOURCE_MODELS:
            raise InventoryPersistenceError("unsupported inventory resource type")
        existing = await self._existing_batch(sync.id, batch)
        if existing is not None:
            if existing.checksum != batch.checksum:
                raise InventoryBatchConflictError("inventory batch checksum conflict")
            return existing

        row = InventoryBatch(
            id=new_uuid7(),
            sync_id=sync.id,
            message_id=message_id,
            resource_type=batch.resource_type.value,
            sequence=batch.sequence,
            is_last=batch.is_last,
            collection_status=batch.collection_status.value,
            item_count=batch.item_count,
            checksum=batch.checksum,
            payload=batch.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.flush()
        if batch.collection_status is InventoryCollectionStatus.COMPLETE:
            for item in batch.items:
                await self._upsert_resource(
                    model=RESOURCE_MODELS[batch.resource_type.value],
                    provider_connection_id=provider_connection_id,
                    sync_id=sync.id,
                    item=item.model_dump(mode="json", exclude_none=True),
                )
        if batch.is_last:
            summary = (
                sync.skipped_collections
                if batch.collection_status is InventoryCollectionStatus.SKIPPED_UNSUPPORTED
                else sync.completed_collections
            )
            if batch.resource_type.value not in summary:
                summary.append(batch.resource_type.value)
        return row

    async def finalize_full_sync(self, sync_id: uuid.UUID) -> InventorySync:
        sync = await self.get_sync(sync_id)
        if sync is None:
            raise InventoryPersistenceError("inventory sync not found")
        expected = set(sync.expected_collections)
        if sync.sync_type != "FULL":
            raise InventorySyncIncompleteError("only full syncs can finalize reconciliation")
        if sync.failed_collections:
            raise InventorySyncIncompleteError("inventory sync has failed collections")
        batches = list(
            (
                await self._session.execute(
                    select(InventoryBatch)
                    .where(InventoryBatch.sync_id == sync_id)
                    .order_by(InventoryBatch.resource_type, InventoryBatch.sequence)
                )
            ).scalars()
        )
        grouped: dict[str, list[InventoryBatch]] = {}
        for batch in batches:
            grouped.setdefault(batch.resource_type, []).append(batch)
        for resource_type in expected:
            collection = grouped.get(resource_type, [])
            if (
                not collection
                or [row.sequence for row in collection] != list(range(1, len(collection) + 1))
                or not collection[-1].is_last
            ):
                raise InventorySyncIncompleteError("inventory sync collection is incomplete")
            if collection[-1].collection_status not in {"COMPLETE", "SKIPPED_UNSUPPORTED"}:
                raise InventorySyncIncompleteError("inventory sync collection status is invalid")
        for resource_type, model in RESOURCE_MODELS.items():
            if resource_type not in expected or resource_type in set(sync.skipped_collections):
                continue
            await self._session.execute(
                update(model)
                .where(
                    model.provider_connection_id == sync.provider_connection_id,
                    model.lifecycle_state == "ACTIVE",
                    model.last_sync_id != sync.id,
                )
                .values(lifecycle_state="DELETED", deleted_at=datetime.now(UTC))
            )
        sync.state = "SUCCEEDED"
        sync.completed_at = datetime.now(UTC)
        await self._session.flush()
        return sync

    async def finalize_sync(self, sync_id: uuid.UUID) -> InventorySync:
        sync = await self.get_sync(sync_id)
        if sync is None:
            raise InventoryPersistenceError("inventory sync not found")
        if sync.sync_type == "FULL":
            return await self.finalize_full_sync(sync_id)
        expected = set(sync.expected_collections)
        batches = list(
            (
                await self._session.execute(
                    select(InventoryBatch)
                    .where(InventoryBatch.sync_id == sync_id)
                    .order_by(InventoryBatch.resource_type, InventoryBatch.sequence)
                )
            ).scalars()
        )
        grouped = {key: [row for row in batches if row.resource_type == key] for key in expected}
        if not expected or any(
            not rows
            or [row.sequence for row in rows] != list(range(1, len(rows) + 1))
            or not rows[-1].is_last
            for rows in grouped.values()
        ):
            raise InventorySyncIncompleteError("targeted inventory refresh is incomplete")
        sync.state = "SUCCEEDED"
        sync.completed_at = datetime.now(UTC)
        await self._session.flush()
        return sync

    async def _existing_batch(
        self, sync_id: uuid.UUID, batch: InventoryBatchPayload
    ) -> InventoryBatch | None:
        result = await self._session.execute(
            select(InventoryBatch).where(
                InventoryBatch.sync_id == sync_id,
                InventoryBatch.resource_type == batch.resource_type.value,
                InventoryBatch.sequence == batch.sequence,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_resource(
        self,
        *,
        model: type[Any],
        provider_connection_id: uuid.UUID,
        sync_id: uuid.UUID,
        item: dict[str, Any],
    ) -> None:
        try:
            item = canonicalize_inventory_item(item)
        except ValidationError as exc:
            if any(error.get("type") == "ownership_conflict" for error in exc.errors()):
                raise InventoryPersistenceError(OWNERSHIP_CONFLICT_MESSAGE) from exc
            raise InventoryPersistenceError("inventory item failed canonical validation") from exc
        now = datetime.now(UTC)
        # Identity resources are provider-global.  When an administrative
        # resource is observed through another project-scoped connection,
        # retain the first CPS row as the canonical owner instead of creating
        # a second row keyed only by the observing connection.
        if model in (IdentityDomain, Project):
            current_provider = await self._session.scalar(
                select(ProviderConnection.provider_id).where(
                    ProviderConnection.id == provider_connection_id
                )
            )
            if current_provider is not None:
                canonical = await self._session.execute(
                    select(model.provider_connection_id)
                    .join(
                        ProviderConnection,
                        ProviderConnection.id == model.provider_connection_id,
                    )
                    .where(
                        model.provider_resource_id == item["provider_resource_id"],
                        ProviderConnection.provider_id == current_provider,
                    )
                    .limit(1)
                )
                canonical_connection_id = canonical.scalar_one_or_none()
                if canonical_connection_id is not None:
                    provider_connection_id = canonical_connection_id
        values: dict[str, Any] = {
            "id": new_uuid7(),
            "provider_connection_id": provider_connection_id,
            "provider_resource_id": item["provider_resource_id"],
            "name": item["name"],
            "provider_status": item.get("provider_status"),
            "provider_created_at": _parse_provider_timestamp(item.get("provider_created_at")),
            "provider_updated_at": _parse_provider_timestamp(item.get("provider_updated_at")),
            "last_seen_at": now,
            "last_sync_id": sync_id,
            "lifecycle_state": item.get("lifecycle_state", "ACTIVE"),
            "deleted_at": None,
            "provider_attributes": copy.deepcopy(item.get("attributes", {})),
        }
        attrs = item.get("attributes", {})
        try:
            owner_project_id = resolve_owner_project_provider_resource_id(item, attrs)
        except OwnershipConflictError as exc:
            raise InventoryPersistenceError(str(exc)) from exc
        except ValueError as exc:
            raise InventoryPersistenceError(str(exc)) from exc
        if model is not Project and hasattr(model, "project_id"):
            if owner_project_id is not None:
                values["project_provider_resource_id"] = owner_project_id
                values["project_id"] = await self._resolve_project_id(
                    provider_connection_id, owner_project_id
                )
        # Promote identity ownership fields to typed columns while retaining
        # provider_attributes for provider-specific data.
        if model is Project:
            provider_id = await self._session.scalar(
                select(ProviderConnection.provider_id).where(
                    ProviderConnection.id == provider_connection_id
                )
            )
            values["provider_id"] = provider_id
            values["org_id"] = item.get("org_id") or attrs.get("org_id")
            values["workspace_id"] = item.get("workspace_id") or attrs.get("workspace_id")
            values["ownership_state"] = (
                "MANAGED" if values["org_id"] and values["workspace_id"] else "UNBOUND"
            )
            values["domain_provider_resource_id"] = item.get(
                "domain_provider_resource_id"
            ) or item.get("attributes", {}).get("domain_provider_resource_id")
            values["domain_name"] = item.get("domain_name") or item.get("attributes", {}).get(
                "domain_name"
            )
            values["owner_domain_provider_resource_id"] = item.get(
                "owner_domain_provider_resource_id"
            ) or item.get("attributes", {}).get("owner_domain_provider_resource_id")
            values["owner_project_provider_resource_id"] = item.get(
                "owner_project_provider_resource_id"
            ) or item.get("attributes", {}).get("owner_project_provider_resource_id")
            values["enabled"] = (
                item.get("enabled")
                if "enabled" in item
                else item.get("attributes", {}).get("enabled")
            )
        if model is IdentityDomain:
            values["enabled"] = (
                item.get("enabled")
                if "enabled" in item
                else item.get("attributes", {}).get("enabled")
            )
        if model is RoleAssignment:
            attrs = item.get("attributes", {})
            values.update(
                principal_type=item.get("principal_type", attrs.get("principal_type", "user")),
                principal_provider_resource_id=item.get(
                    "principal_provider_resource_id",
                    attrs.get("principal_provider_resource_id", item["provider_resource_id"]),
                ),
                role_provider_resource_id=item.get(
                    "role_provider_resource_id", attrs.get("role_provider_resource_id", "unknown")
                ),
                scope_kind=item.get("scope_kind", attrs.get("scope_kind", "PROJECT")),
                scope_provider_resource_id=item.get(
                    "scope_provider_resource_id", attrs.get("scope_provider_resource_id")
                ),
                inherited=bool(item.get("inherited", attrs.get("inherited", False))),
            )
        if model is Quota:
            attrs = item.get("attributes", {})
            raw_limit = item.get("limit_value", attrs.get("limit_value"))
            unlimited = bool(item.get("unlimited", attrs.get("unlimited", raw_limit == -1)))
            values.update(
                service=item.get("service", attrs.get("service", "unknown")),
                resource_name=item.get("resource_name", attrs.get("resource_name", item["name"])),
                limit_value=None if unlimited else raw_limit,
                in_use=item.get("in_use", attrs.get("in_use")),
                unlimited=unlimited,
            )
        if model is AvailabilityZone:
            values["available"] = item.get("available", attrs.get("available"))
        if model is VolumeType:
            values["is_public"] = item.get("is_public", attrs.get("is_public"))
        if model is Volume:
            values.update(
                size_gib=item.get("size_gib", attrs.get("size")),
                volume_type=item.get("volume_type", attrs.get("volume_type")),
                volume_type_provider_resource_id=item.get(
                    "volume_type_provider_resource_id", attrs.get("volume_type")
                ),
                bootable=item.get("bootable", attrs.get("bootable")),
                root=item.get("root", attrs.get("root")),
                encrypted=item.get("encrypted", attrs.get("encrypted")),
                multiattach=item.get("multiattach", attrs.get("multiattach")),
                availability_zone=item.get("availability_zone", attrs.get("availability_zone")),
                metadata_values=item.get("metadata", attrs.get("metadata", {})),
                attachments=item.get("attachments", attrs.get("attachments", [])),
            )
        if model is VolumeSnapshot:
            values.update(
                volume_provider_resource_id=item.get(
                    "volume_provider_resource_id", attrs.get("volume_id")
                ),
                size_gib=item.get("snapshot_size_gib", attrs.get("size")),
                metadata_values=item.get("metadata", attrs.get("metadata", {})),
            )
        if model is Keypair:
            values.update(
                fingerprint=item.get("fingerprint", attrs.get("fingerprint")),
                key_type=item.get("key_type", attrs.get("type")),
                public_key=item.get("public_key", attrs.get("public_key")),
            )
        if model is Image:
            values.update(
                visibility=item.get("visibility"),
                size_bytes=item.get("size_bytes"),
                min_disk_gib=item.get("min_disk_gib"),
                min_ram_mib=item.get("min_ram_mib"),
                disk_format=item.get("disk_format"),
                checksum=item.get("checksum"),
            )
        if model is Flavor:
            values.update(
                vcpus=item.get("vcpus"),
                ram_mib=item.get("ram_mib"),
                root_disk_gib=item.get("root_disk_gib"),
                ephemeral_disk_gib=item.get("ephemeral_disk_gib"),
                swap_mib=item.get("swap_mib"),
                is_public=item.get("is_public"),
                enabled=item.get("enabled"),
            )
        statement = pg_insert(model).values(**values)
        conflict_set: dict[str, Any] = {
            "name": statement.excluded.name,
            "provider_status": statement.excluded.provider_status,
            "last_seen_at": statement.excluded.last_seen_at,
            "last_sync_id": statement.excluded.last_sync_id,
            "lifecycle_state": statement.excluded.lifecycle_state,
            "deleted_at": now if item.get("lifecycle_state") == "DELETED" else None,
            "provider_attributes": statement.excluded.provider_attributes,
            "updated_at": now,
        }
        if model is Project:
            conflict_set.update(
                {
                    "domain_provider_resource_id": statement.excluded.domain_provider_resource_id,
                    "domain_name": statement.excluded.domain_name,
                    "owner_domain_provider_resource_id": (
                        statement.excluded.owner_domain_provider_resource_id
                    ),
                    "owner_project_provider_resource_id": (
                        statement.excluded.owner_project_provider_resource_id
                    ),
                    "enabled": statement.excluded.enabled,
                    "provider_id": statement.excluded.provider_id,
                }
            )
        elif model in (
            RoleAssignment,
            Quota,
            AvailabilityZone,
            VolumeType,
            Volume,
            VolumeSnapshot,
            Keypair,
            Image,
            Flavor,
        ):
            # Keep all typed fields synchronized while preserving the generic
            # provider attributes used by older consumers.
            typed = {
                c.name: statement.excluded[c.name]
                for c in model.__table__.columns
                if c.name in values
                and c.name not in {"id", "provider_connection_id", "provider_resource_id"}
            }
            typed.update({"updated_at": now})
            if hasattr(model, "project_id"):
                typed.update(_project_ownership_conflict_update(model, statement))
            conflict_set = typed
        elif hasattr(model, "project_id") and model is not Quota:
            conflict_set.update(
                {
                    "project_id": sa.func.coalesce(statement.excluded.project_id, model.project_id),
                    "project_provider_resource_id": sa.func.coalesce(
                        statement.excluded.project_provider_resource_id,
                        model.project_provider_resource_id,
                    ),
                }
            )
        elif model is IdentityDomain:
            conflict_set["enabled"] = statement.excluded.enabled
        statement = statement.on_conflict_do_update(
            index_elements=["provider_connection_id", "provider_resource_id"],
            set_=conflict_set,
        )
        await self._session.execute(statement)
