from types import SimpleNamespace
from uuid import uuid4

import pytest

from cps.api.schemas.connections import ConnectionCreate, ConnectionPatch
from cps.application.connections import ConnectionService
from cps.contracts.errors import InvalidRequestError
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus


def _create(**kwargs):
    values = {
        "credential_id": uuid4(),
        "auth_url": "https://keystone.example/v3",
        "project_name": "demo",
        "region_name": "RegionOne",
    }
    values.update(kwargs)
    return ConnectionCreate.model_validate(values)


@pytest.mark.parametrize(
    ("scope_kind", "domain_id", "project_id"),
    [
        (ConnectionScopeKind.SYSTEM, None, None),
        (ConnectionScopeKind.DOMAIN, "domain-1", None),
        (ConnectionScopeKind.PROJECT, "domain-1", "project-1"),
        (ConnectionScopeKind.PROJECT, None, None),  # legacy project-name compatibility
    ],
)
def test_supported_scope_combinations_are_accepted(scope_kind, domain_id, project_id):
    value = _create(
        scope_kind=scope_kind,
        scope_domain_provider_resource_id=domain_id,
        scope_project_provider_resource_id=project_id,
    )
    assert value.scope_kind is scope_kind


def test_system_scope_cannot_bind_project():
    with pytest.raises(ValueError, match="SYSTEM"):
        _create(
            scope_kind=ConnectionScopeKind.SYSTEM,
            scope_project_provider_resource_id="project-1",
        )


@pytest.mark.asyncio
async def test_validated_connection_scope_is_immutable():
    connection = SimpleNamespace(status=ConnectionStatus.VALID, version=1)

    class Repository:
        async def get_connection(self, _):
            return connection

    with pytest.raises(InvalidRequestError, match="scope"):
        await ConnectionService(Repository()).update(
            uuid4(),
            ConnectionPatch(
                expected_version=1,
                scope_kind=ConnectionScopeKind.SYSTEM,
            ),
        )
