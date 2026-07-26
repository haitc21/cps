"""Explicit provider identity binding application service."""

from __future__ import annotations

import uuid

from cps.api.schemas.bindings import (
    IdentityDomainBindingCreate,
    IdentityProjectBindingCreate,
)
from cps.api.schemas.operations import OperationView
from cps.application.operations import OperationApplicationService
from cps.contracts.errors import (
    CapabilityUnsupportedError,
    DomainConflictError,
    InvalidRequestError,
    ProviderNotFoundError,
)
from cps.contracts.messages.identity import IdentityOperation, IdentityResourceRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus
from cps.infrastructure.db.models.identity_bindings import IdentityBinding
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.repositories.identity_bindings import IdentityBindingRepository
from cps.infrastructure.db.repositories.providers import ProviderRepository


class IdentityBindingService:
    def __init__(
        self,
        providers: ProviderRepository,
        bindings: IdentityBindingRepository,
        operations: OperationApplicationService,
    ) -> None:
        self._providers = providers
        self._bindings = bindings
        self._operations = operations

    async def create_domain(
        self,
        provider_id: uuid.UUID,
        body: IdentityDomainBindingCreate,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
    ) -> tuple[object, OperationView]:
        existing = await self._bindings.get_domain(provider_id, body.org_id)
        if existing is not None:
            if existing.provider_resource_name != body.name:
                raise DomainConflictError("identity domain binding already exists")
            return existing, await self._operation_from_binding(existing)
        provider, connection, _credential = await self._provider_aggregate(provider_id)
        binding_id = new_uuid7()
        request = IdentityResourceRequest(
            operation_id=new_uuid7(),
            resource_type="domain",
            operation=IdentityOperation.CREATE,
            required_scope=ScopeKind.SYSTEM,
            provider_connection_id=connection.id,
            name=body.name,
            description=body.description,
            org_id=body.org_id,
            binding_id=binding_id,
        )
        operation = await self._operations.create_identity_operation(
            connection.id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            request=request,
        )
        binding = await self._bindings.add_pending(
            binding_id=binding_id,
            provider_id=provider.id,
            provider_connection_id=connection.id,
            operation_id=operation.id,
            binding_kind="OPENSTACK_DOMAIN",
            org_id=body.org_id,
            workspace_id=None,
            provider_resource_name=body.name,
        )
        return binding, operation

    async def create_project(
        self,
        provider_id: uuid.UUID,
        body: IdentityProjectBindingCreate,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
    ) -> tuple[object, OperationView]:
        existing = await self._bindings.get_project(provider_id, body.org_id, body.workspace_id)
        if existing is not None:
            if existing.provider_resource_name != body.name:
                raise DomainConflictError("identity project binding already exists")
            return existing, await self._operation_from_binding(existing)
        domain = await self._bindings.get_domain(provider_id, body.org_id)
        if domain is None:
            raise InvalidRequestError("identity domain binding is required first")
        provider, connection, _credential = await self._provider_aggregate(provider_id)
        binding_id = new_uuid7()
        request = IdentityResourceRequest(
            operation_id=new_uuid7(),
            resource_type="project",
            operation=IdentityOperation.CREATE,
            required_scope=ScopeKind.SYSTEM,
            provider_connection_id=connection.id,
            name=body.name,
            description=body.description,
            domain_provider_resource_id=domain.provider_resource_id,
            org_id=body.org_id,
            workspace_id=body.workspace_id,
            binding_id=binding_id,
        )
        operation = await self._operations.create_identity_operation(
            connection.id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            request=request,
        )
        binding = await self._bindings.add_pending(
            binding_id=binding_id,
            provider_id=provider.id,
            provider_connection_id=connection.id,
            operation_id=operation.id,
            binding_kind="OPENSTACK_PROJECT",
            org_id=body.org_id,
            workspace_id=body.workspace_id,
            provider_resource_name=body.name,
        )
        return binding, operation

    async def _provider_aggregate(
        self, provider_id: uuid.UUID
    ) -> tuple[Provider, ProviderConnection, Credential]:
        aggregate = await self._providers.get_provider_aggregate(provider_id)
        if aggregate is None:
            raise ProviderNotFoundError
        provider, connection, credential = aggregate
        if provider.status is not ProviderStatus.ACTIVE:
            raise CapabilityUnsupportedError("provider is disabled")
        if connection.status is not ConnectionStatus.VALID:
            raise CapabilityUnsupportedError("provider connection must be validated")
        return provider, connection, credential

    async def _operation_from_binding(self, binding: IdentityBinding) -> OperationView:
        # Existing idempotent bindings do not need to enqueue a second mutation.
        return OperationView.model_validate(
            {
                "id": binding.operation_id or new_uuid7(),
                "provider_connection_id": binding.provider_connection_id,
                "operation_type": "identity.binding.ensure",
                "state": "SUCCEEDED",
                "progress_percent": 100,
                "idempotency_key": None,
                "request_payload": {},
                "result_payload": {"binding_id": str(binding.id)},
                "error_payload": None,
                "correlation_id": new_uuid7(),
                "causation_id": None,
                "actor_context": None,
                "provider_request_id": None,
                "timeout_at": None,
                "version": 1,
                "created_at": binding.created_at,
                "updated_at": binding.updated_at,
                "completed_at": binding.updated_at,
            }
        )
