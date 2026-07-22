"""Domain invariants for transactional outbox messages."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cps.contracts.messages.delivery import DEFAULT_MAX_ATTEMPTS
from cps.domain.messaging.outbox import OutboxDraft, OutboxValidationError
from cps.domain.operations.create import create_operation_idempotent
from cps.domain.operations.errors import OperationPersistenceError
from cps.identifiers import new_uuid7


def _draft(*, routing_key: str = "openstack.connection.validate") -> OutboxDraft:
    now = datetime.now(UTC)
    message_id = new_uuid7()
    correlation_id = new_uuid7()
    operation_id = new_uuid7()
    return OutboxDraft(
        aggregate_type="operation",
        aggregate_id=operation_id,
        message_id=message_id,
        message_type="openstack.connection.validate",
        routing_key=routing_key,
        payload={
            "message_id": str(message_id),
            "message_type": "openstack.connection.validate",
            "schema_version": "1.0",
            "occurred_at": now.isoformat(),
            "correlation_id": str(correlation_id),
            "operation_id": str(operation_id),
            "provider_id": str(new_uuid7()),
            "provider_connection_id": str(new_uuid7()),
        },
        correlation_id=correlation_id,
        occurred_at=now,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
    )


def test_outbox_draft_copies_payload_and_uses_command_routing() -> None:
    draft = _draft()

    assert draft.payload["payload"] == {}
    assert draft.delivery_metadata.attempt == 1


def test_outbox_draft_rejects_event_routing_key() -> None:
    with pytest.raises(OutboxValidationError, match="command routing key"):
        _draft(routing_key="cloud.operation.completed")


def test_outbox_draft_requires_utc_timestamp() -> None:
    draft = _draft()
    with pytest.raises(OutboxValidationError, match="UTC"):
        OutboxDraft(
            aggregate_type="operation",
            aggregate_id=new_uuid7(),
            message_id=draft.message_id,
            message_type="openstack.connection.validate",
            routing_key="openstack.connection.validate",
            payload=draft.payload,
            correlation_id=draft.correlation_id,
            occurred_at=datetime.now(),
        )


@pytest.mark.parametrize("max_attempts", [2, 4])
def test_outbox_draft_rejects_noncanonical_max_attempts(max_attempts: int) -> None:
    draft = _draft()
    with pytest.raises(OutboxValidationError, match="canonical default"):
        OutboxDraft(
            aggregate_type=draft.aggregate_type,
            aggregate_id=draft.aggregate_id,
            message_id=draft.message_id,
            message_type=draft.message_type,
            routing_key=draft.routing_key,
            payload=draft.payload,
            correlation_id=draft.correlation_id,
            occurred_at=draft.occurred_at,
            max_attempts=max_attempts,
        )


@pytest.mark.parametrize("field", ["message_id", "message_type", "correlation_id", "operation_id"])
def test_outbox_draft_rejects_envelope_identity_mismatch_without_payload_leak(field: str) -> None:
    draft = _draft()
    payload = dict(draft.payload)
    payload[field] = "synthetic-password-token" if field == "message_type" else str(new_uuid7())
    with pytest.raises(OutboxValidationError) as raised:
        OutboxDraft(
            aggregate_type=draft.aggregate_type,
            aggregate_id=draft.aggregate_id,
            message_id=draft.message_id,
            message_type=draft.message_type,
            routing_key=draft.routing_key,
            payload=payload,
            correlation_id=draft.correlation_id,
            occurred_at=draft.occurred_at,
        )
    assert "synthetic-password-token" not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message_id", new_uuid7()),
        ("correlation_id", new_uuid7()),
        ("message_type", "openstack.server.create"),
        ("aggregate_id", new_uuid7()),
    ],
)
def test_outbox_draft_rejects_top_level_identity_mismatch_with_valid_envelope(
    field: str,
    value: object,
) -> None:
    draft = _draft()

    with pytest.raises(OutboxValidationError) as raised:
        replace(draft, **{field: value})

    assert "synthetic-password-token" not in str(raised.value)


@pytest.mark.asyncio
async def test_supplied_uuidv4_operation_id_is_rejected() -> None:
    with pytest.raises(OperationPersistenceError, match="operation id must be UUIDv7"):
        await create_operation_idempotent(
            object(),  # type: ignore[arg-type]
            provider_connection_id=new_uuid7(),
            operation_type="openstack.connection.validate",
            request_payload={},
            correlation_id=new_uuid7(),
            operation_id=uuid.uuid4(),
        )
