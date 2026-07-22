"""Shared helpers for inbox integration tests."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cps.contracts.messages.delivery import (
    HEADER_ATTEMPT,
    HEADER_CORRELATION_ID,
    HEADER_MAX_ATTEMPTS,
    HEADER_MESSAGE_ID,
    HEADER_TRANSPORT_VERSION,
    SUPPORTED_TRANSPORT_VERSION,
)
from cps.domain.messaging.inbox import InboxReceiveDraft
from cps.domain.operations.inbox_handler import OperationInboxHandler
from cps.domain.operations.service import OperationService
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "src" / "cps" / "contracts" / "fixtures" / "events"
)
CONSUMER_NAME = "cps.cloud.event.v1"


def load_event_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def bind_fixture_to_operation(
    fixture: dict[str, Any],
    *,
    operation_id: uuid.UUID,
    provider_id: uuid.UUID,
    provider_connection_id: uuid.UUID,
    message_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(fixture)
    message_id = message_id or new_uuid7()
    payload["message_id"] = str(message_id)
    payload["operation_id"] = str(operation_id)
    payload["provider_id"] = str(provider_id)
    payload["provider_connection_id"] = str(provider_connection_id)
    return payload


def delivery_headers(
    *,
    message_id: uuid.UUID,
    correlation_id: uuid.UUID,
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        HEADER_TRANSPORT_VERSION: SUPPORTED_TRANSPORT_VERSION,
        HEADER_MESSAGE_ID: str(message_id),
        HEADER_CORRELATION_ID: str(correlation_id),
        HEADER_ATTEMPT: attempt,
        HEADER_MAX_ATTEMPTS: 3,
    }


async def advance_operation_to_running(operation_id: uuid.UUID, db_session_factory) -> int:
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
        )
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=2,
            to_state=OperationState.RUNNING,
        )
        await uow.commit()
    return 3


async def process_event_once(
    db_session_factory,
    envelope_dict: dict[str, Any],
    *,
    consumer_name: str = CONSUMER_NAME,
) -> bool:
    from cps.contracts.messages.envelope import MessageEnvelope

    envelope = MessageEnvelope.model_validate(envelope_dict)
    now = datetime.now(UTC)
    occurred_at = envelope.occurred_at
    draft = InboxReceiveDraft(
        consumer_name=consumer_name,
        message_id=envelope.message_id,
        message_type=envelope.message_type,
        payload=envelope.model_dump(mode="json"),
        received_at=occurred_at,
    )
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        insert_result = await uow.inbox.try_insert_received(draft)
        if insert_result.is_duplicate:
            return True
        handler = OperationInboxHandler(uow.operations)
        await handler.handle(envelope)
        assert insert_result.inbox_id is not None
        marked = await uow.inbox.mark_processed(insert_result.inbox_id, now=now)
        assert marked is True
        await uow.commit()
    return False
