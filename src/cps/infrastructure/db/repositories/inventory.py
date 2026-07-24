"""Inventory sync and batch persistence with idempotent ingestion."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cps.contracts.messages.inventory import InventoryBatchPayload, InventoryCollectionStatus
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.inventory import (
    Flavor,
    IdentityDomain,
    Image,
    Instance,
    InstancePort,
    InstanceVolume,
    Network,
    Port,
    Project,
    Region,
    Subnet,
    Volume,
)
from cps.infrastructure.db.models.inventory_sync import InventoryBatch, InventorySync
from cps.infrastructure.db.models.provider_connections import ProviderConnection

RESOURCE_MODELS: dict[str, Any] = {
    "domain": IdentityDomain,
    "region": Region,
    "project": Project,
    "flavor": Flavor,
    "image": Image,
    "instance": Instance,
    "network": Network,
    "subnet": Subnet,
    "port": Port,
    "volume": Volume,
}
RESOURCE_ALIASES = {f"{key}s": key for key in RESOURCE_MODELS}
RESOURCE_ALIASES.update({"identity-domains": "domain", "identity_domain": "domain"})
RESOURCE_ALIASES["indices"] = "instance"


class InventoryPersistenceError(RuntimeError):
    """Stable error for invalid or conflicting inventory persistence."""


class InventoryBatchConflictError(InventoryPersistenceError):
    """A replayed batch identity has different immutable content."""


class InventorySyncIncompleteError(InventoryPersistenceError):
    """A sync cannot finalize because collection integrity is incomplete."""


class InventoryRepository:
    """Repository whose caller owns the transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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

    async def list_resources(
        self,
        resource_type: str,
        *,
        offset: int,
        limit: int,
        provider_connection_id: uuid.UUID | None = None,
        provider_resource_id: str | None = None,
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
            "last_seen_at": now,
            "last_sync_id": sync_id,
            "lifecycle_state": item.get("lifecycle_state", "ACTIVE"),
            "deleted_at": None,
            "provider_attributes": copy.deepcopy(item.get("attributes", {})),
        }
        # Promote identity ownership fields to typed columns while retaining
        # provider_attributes for provider-specific data.
        if model is Project:
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
        statement = pg_insert(model).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["provider_connection_id", "provider_resource_id"],
            set_={
                "name": statement.excluded.name,
                "provider_status": statement.excluded.provider_status,
                "last_seen_at": statement.excluded.last_seen_at,
                "last_sync_id": statement.excluded.last_sync_id,
                "lifecycle_state": statement.excluded.lifecycle_state,
                "deleted_at": now if item.get("lifecycle_state") == "DELETED" else None,
                "provider_attributes": statement.excluded.provider_attributes,
                "updated_at": now,
            },
        )
        if model is Project:
            statement = statement.on_conflict_do_update(
                index_elements=["provider_connection_id", "provider_resource_id"],
                set_={
                    "name": statement.excluded.name,
                    "provider_status": statement.excluded.provider_status,
                    "last_seen_at": statement.excluded.last_seen_at,
                    "last_sync_id": statement.excluded.last_sync_id,
                    "lifecycle_state": statement.excluded.lifecycle_state,
                    "deleted_at": now if item.get("lifecycle_state") == "DELETED" else None,
                    "provider_attributes": statement.excluded.provider_attributes,
                    "domain_provider_resource_id": statement.excluded.domain_provider_resource_id,
                    "domain_name": statement.excluded.domain_name,
                    "owner_domain_provider_resource_id": (
                        statement.excluded.owner_domain_provider_resource_id
                    ),
                    "owner_project_provider_resource_id": (
                        statement.excluded.owner_project_provider_resource_id
                    ),
                    "enabled": statement.excluded.enabled,
                    "updated_at": now,
                },
            )
        elif model is IdentityDomain:
            statement = statement.on_conflict_do_update(
                index_elements=["provider_connection_id", "provider_resource_id"],
                set_={
                    "name": statement.excluded.name,
                    "provider_status": statement.excluded.provider_status,
                    "last_seen_at": statement.excluded.last_seen_at,
                    "last_sync_id": statement.excluded.last_sync_id,
                    "lifecycle_state": statement.excluded.lifecycle_state,
                    "deleted_at": now if item.get("lifecycle_state") == "DELETED" else None,
                    "provider_attributes": statement.excluded.provider_attributes,
                    "enabled": statement.excluded.enabled,
                    "updated_at": now,
                },
            )
        await self._session.execute(statement)
