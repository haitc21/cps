"""Persistence for explicit CMP identity ownership bindings."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.identity_bindings import IdentityBinding
from cps.infrastructure.db.models.inventory import Project


class IdentityBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, binding_id: uuid.UUID) -> IdentityBinding | None:
        return await self._session.get(IdentityBinding, binding_id)

    async def get_domain(self, provider_id: uuid.UUID, org_id: str) -> IdentityBinding | None:
        result = await self._session.execute(
            select(IdentityBinding).where(
                IdentityBinding.provider_id == provider_id,
                IdentityBinding.org_id == org_id,
                IdentityBinding.binding_kind == "OPENSTACK_DOMAIN",
            )
        )
        return result.scalar_one_or_none()

    async def get_project(
        self, provider_id: uuid.UUID, org_id: str, workspace_id: str
    ) -> IdentityBinding | None:
        result = await self._session.execute(
            select(IdentityBinding).where(
                IdentityBinding.provider_id == provider_id,
                IdentityBinding.org_id == org_id,
                IdentityBinding.workspace_id == workspace_id,
                IdentityBinding.binding_kind == "OPENSTACK_PROJECT",
            )
        )
        return result.scalar_one_or_none()

    async def add_pending(
        self,
        *,
        binding_id: uuid.UUID,
        provider_id: uuid.UUID,
        provider_connection_id: uuid.UUID,
        operation_id: uuid.UUID,
        binding_kind: str,
        org_id: str,
        workspace_id: str | None,
        provider_resource_name: str,
    ) -> IdentityBinding:
        binding = IdentityBinding(
            id=binding_id,
            provider_id=provider_id,
            provider_connection_id=provider_connection_id,
            operation_id=operation_id,
            provider_type="OPENSTACK",
            binding_kind=binding_kind,
            org_id=org_id,
            workspace_id=workspace_id,
            provider_resource_name=provider_resource_name,
            status="PENDING",
            version=1,
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def apply_result(
        self,
        binding_id: uuid.UUID,
        *,
        provider_resource_id: str | None,
        resource: dict[str, Any] | None,
        error: dict[str, Any] | None = None,
    ) -> IdentityBinding | None:
        binding = await self.get(binding_id)
        if binding is None:
            return None
        if error is not None:
            binding.status = "FAILED"
            binding.last_error_code = str(error.get("code", "PROVIDER_ERROR"))[:128]
            binding.last_error_message = "Provider identity operation failed"
        else:
            binding.status = "READY"
            binding.provider_resource_id = provider_resource_id
            if resource and isinstance(resource.get("name"), str):
                binding.provider_resource_name = resource["name"]
            binding.last_error_code = None
            binding.last_error_message = None
            if binding.binding_kind == "OPENSTACK_PROJECT" and provider_resource_id is not None:
                await self._project_canonical_ownership(binding, provider_resource_id)
        binding.version += 1
        await self._session.flush()
        return binding

    async def _project_canonical_ownership(
        self, binding: IdentityBinding, provider_resource_id: str
    ) -> None:
        """Project a READY project binding into the canonical inventory row."""
        if binding.workspace_id is None:
            return
        now = datetime.now(UTC)
        values = {
            "id": new_uuid7(),
            "provider_connection_id": binding.provider_connection_id,
            "provider_id": binding.provider_id,
            "provider_resource_id": provider_resource_id,
            "name": binding.provider_resource_name,
            "org_id": binding.org_id,
            "workspace_id": binding.workspace_id,
            "ownership_state": "MANAGED",
            "lifecycle_state": "ACTIVE",
            "provider_attributes": {},
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        statement = pg_insert(Project).values(**values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["provider_connection_id", "provider_resource_id"],
                set_={
                    "org_id": statement.excluded.org_id,
                    "workspace_id": statement.excluded.workspace_id,
                    "ownership_state": statement.excluded.ownership_state,
                    "name": statement.excluded.name,
                    "updated_at": now,
                },
            )
        )

    async def mark_deleted(self, binding_id: uuid.UUID) -> IdentityBinding | None:
        binding = await self.get(binding_id)
        if binding is None:
            return None
        binding.status = "DELETED"
        binding.provider_resource_id = None
        binding.last_error_code = None
        binding.last_error_message = None
        binding.version += 1
        await self._session.flush()
        return binding
