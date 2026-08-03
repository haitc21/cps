"""Security and durability coverage for CPS-1903 image commands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application.operations import OperationApplicationService
from cps.contracts.messages.image_operations import ImageOperationRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import OperationState


class _Repository:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection
        self.operations: dict[tuple[uuid.UUID, str, str], SimpleNamespace] = {}

    async def get_provider_connection(self, connection_id: uuid.UUID):
        return self.connection if connection_id == self.connection.id else None

    async def get_by_idempotency_scope(self, **kwargs):
        return self.operations.get(
            (kwargs["provider_connection_id"], kwargs["operation_type"], kwargs["idempotency_key"])
        )

    async def insert_operation(self, **kwargs):
        operation = SimpleNamespace(
            **kwargs,
            id=kwargs["operation_id"],
            state=OperationState.ACCEPTED,
            version=1,
            progress_percent=None,
            result_payload=None,
            error_payload=None,
            provider_request_id=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.operations[
            (kwargs["provider_connection_id"], kwargs["operation_type"], kwargs["idempotency_key"])
        ] = operation
        return operation


class _Outbox:
    def __init__(self) -> None:
        self.drafts = []

    async def add(self, draft) -> None:
        self.drafts.append(draft)


@pytest.mark.parametrize(
    "source_url",
    [
        "http://images.example.test/a.qcow2",
        "https://user" + ":" + "pass@images.example.test/a.qcow2",
        "https://images.example.test/a.qcow2?sig=not-allowed",
        "file:///etc/passwd",
        "data:image/qcow2;base64,AAAA",
        "https://127.0.0.1/a.qcow2",
        "https://[::1]/a.qcow2",
    ],
)
def test_import_rejects_non_allowlisted_or_secret_bearing_urls(source_url: str) -> None:
    with pytest.raises(ValueError):
        ImageOperationRequest(
            operation_id=uuid.uuid4(),
            operation="import_url",
            provider_connection_id=uuid.uuid4(),
            name="cmp-s19-image",
            source_url=source_url,
            disk_format="qcow2",
        )


def test_image_contract_bounds_metadata_and_rejects_bytes_or_secrets() -> None:
    base = dict(
        operation_id=uuid.uuid4(),
        operation="patch_metadata",
        provider_connection_id=uuid.uuid4(),
        provider_resource_id="img-1",
    )
    with pytest.raises(ValueError):
        ImageOperationRequest(**base, metadata={"api_token": "synthetic"})
    with pytest.raises(ValueError):
        ImageOperationRequest(**base, metadata={"x": "a" * 1025})
    with pytest.raises(ValueError):
        ImageOperationRequest(**base, metadata={"image_bytes": "AAAA"})
    with pytest.raises(ValueError):
        ImageOperationRequest(**base, metadata={"nested": {"no": "objects"}})
    with pytest.raises(ValueError):
        ImageOperationRequest(**base, metadata={str(index): "v" for index in range(51)})


@pytest.mark.asyncio
async def test_image_import_is_capability_gated_durable_and_idempotent(monkeypatch) -> None:
    connection_id = uuid.uuid4()
    connection = SimpleNamespace(
        id=connection_id,
        provider_id=uuid.uuid4(),
        capabilities={"features": {"image.import": {"supported": True}}},
    )
    repo, outbox = _Repository(connection), _Outbox()
    service = OperationApplicationService(repo, outbox)

    async def transition(_service, **kwargs):
        operation = repo.operations[(connection_id, "openstack.image.import", "image-key")]
        operation.state = OperationState.QUEUED
        operation.version += 1
        return operation

    monkeypatch.setattr(OperationService, "transition_operation", transition)
    request = ImageOperationRequest(
        operation_id=uuid.uuid4(),
        operation="import_url",
        provider_connection_id=connection_id,
        required_scope=ScopeKind.SYSTEM,
        name="cmp-s19-image",
        disk_format="qcow2",
        source_url="https://images.example.test/public/cmp.qcow2",
    )
    first = await service.create_image_operation(
        connection_id, idempotency_key="image-key", correlation_id=uuid.uuid4(), request=request
    )
    replay = await service.create_image_operation(
        connection_id, idempotency_key="image-key", correlation_id=uuid.uuid4(), request=request
    )
    assert first.id == replay.id == uuid.uuid5(connection_id, "image:image-key")
    assert len(outbox.drafts) == 1
    assert outbox.drafts[0].message_type == "openstack.image.import"
    payload = outbox.drafts[0].payload["payload"]
    assert "bytes" not in str(payload).lower()
