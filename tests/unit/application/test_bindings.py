"""Explicit provider identity binding application tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.api.schemas.bindings import IdentityDomainBindingCreate, IdentityProjectBindingCreate
from cps.application.bindings import IdentityBindingService
from cps.contracts.errors import InvalidRequestError
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus

NOW = datetime.now(UTC)


class _Bindings:
    def __init__(self, domain=None, project=None) -> None:
        self.domain = domain
        self.project = project
        self.created = []

    async def get_domain(self, _provider_id, _org_id):
        return self.domain

    async def get_project(self, _provider_id, _org_id, _workspace_id):
        return self.project

    async def add_pending(self, **kwargs):
        binding = SimpleNamespace(
            id=kwargs["binding_id"],
            provider_id=kwargs["provider_id"],
            provider_connection_id=kwargs["provider_connection_id"],
            operation_id=kwargs["operation_id"],
            provider_type="OPENSTACK",
            binding_kind=kwargs["binding_kind"],
            org_id=kwargs["org_id"],
            workspace_id=kwargs["workspace_id"],
            provider_resource_id=None,
            provider_resource_name=kwargs["provider_resource_name"],
            status="PENDING",
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        self.created.append(binding)
        return binding


class _Providers:
    def __init__(self):
        self.provider_id = uuid.uuid4()
        self.connection_id = uuid.uuid4()

    async def get_provider_aggregate(self, provider_id):
        if provider_id != self.provider_id:
            return None
        return (
            SimpleNamespace(id=self.provider_id, status=ProviderStatus.ACTIVE),
            SimpleNamespace(id=self.connection_id, status=ConnectionStatus.VALID),
            SimpleNamespace(),
        )


class _Operations:
    def __init__(self):
        self.requests = []

    async def create_identity_operation(self, _connection_id, **kwargs):
        self.requests.append(kwargs["request"])
        return SimpleNamespace(id=uuid.uuid4())


@pytest.mark.asyncio
async def test_project_binding_requires_domain_binding() -> None:
    providers = _Providers()
    with pytest.raises(InvalidRequestError, match="domain binding"):
        await IdentityBindingService(providers, _Bindings(), _Operations()).create_project(
            providers.provider_id,
            IdentityProjectBindingCreate(org_id="org-1", workspace_id="ws-1", name="project-1"),
            idempotency_key="create-project-1",
            correlation_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_domain_binding_carries_explicit_owner_and_binding_id() -> None:
    providers = _Providers()
    bindings = _Bindings()
    operations = _Operations()
    binding, operation = await IdentityBindingService(
        providers, bindings, operations
    ).create_domain(
        providers.provider_id,
        IdentityDomainBindingCreate(org_id="org-1", name="domain-1"),
        idempotency_key="create-domain-1",
        correlation_id=uuid.uuid4(),
    )
    request = operations.requests[0]
    assert binding.status == "PENDING"
    assert binding.provider_id == providers.provider_id
    assert request.org_id == "org-1"
    assert request.binding_id == binding.id
    assert operation.id == binding.operation_id
