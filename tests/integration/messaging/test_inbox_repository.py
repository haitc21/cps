"""Unit tests for inbox repository deduplication."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from cps.domain.messaging.inbox import InboxInsertStatus, InboxReceiveDraft
from cps.identifiers import new_uuid7
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _draft(
    *, consumer_name: str = "cps.cloud.event.v1", message_id: uuid.UUID | None = None
) -> InboxReceiveDraft:
    message_id = message_id or new_uuid7()
    return InboxReceiveDraft(
        consumer_name=consumer_name,
        message_id=message_id,
        message_type="cloud.operation.progress",
        payload={
            "message_id": str(message_id),
            "message_type": "cloud.operation.progress",
            "schema_version": "1.0",
            "occurred_at": datetime.now(UTC).isoformat(),
            "correlation_id": str(new_uuid7()),
            "operation_id": str(new_uuid7()),
            "provider_id": str(new_uuid7()),
            "provider_connection_id": str(new_uuid7()),
            "payload": {"progress": 10},
        },
        received_at=datetime.now(UTC),
    )


async def test_insert_received_returns_uuidv7_id(db_session_factory) -> None:
    draft = _draft()
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        result = await uow.inbox.try_insert_received(draft)
        await uow.commit()
    assert result.status is InboxInsertStatus.INSERTED
    assert result.inbox_id is not None
    assert result.inbox_id.version == 7


async def test_duplicate_insert_returns_already_processed(db_session_factory) -> None:
    message_id = new_uuid7()
    draft = _draft(message_id=message_id)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        first = await uow.inbox.try_insert_received(draft)
        assert first.inbox_id is not None
        marked = await uow.inbox.mark_processed(first.inbox_id, now=datetime.now(UTC))
        assert marked is True
        await uow.commit()

    second_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with second_uow:
        second = await second_uow.inbox.try_insert_received(draft)
        assert second.status is InboxInsertStatus.ALREADY_PROCESSED


async def test_incoming_message_id_is_preserved(db_session_factory) -> None:
    message_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    draft = _draft(message_id=message_id)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        result = await uow.inbox.try_insert_received(draft)
        row = await uow.inbox.get_by_consumer_message(
            consumer_name=draft.consumer_name,
            message_id=message_id,
        )
        await uow.commit()
    assert row is not None
    assert row.message_id == message_id
    assert result.inbox_id != message_id


async def test_different_consumer_name_allows_same_message_id(db_session_factory) -> None:
    message_id = new_uuid7()
    draft_a = _draft(message_id=message_id, consumer_name="consumer-a")
    draft_b = _draft(message_id=message_id, consumer_name="consumer-b")
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        first = await uow.inbox.try_insert_received(draft_a)
        second = await uow.inbox.try_insert_received(draft_b)
        await uow.commit()
    assert first.status is InboxInsertStatus.INSERTED
    assert second.status is InboxInsertStatus.INSERTED
    assert first.inbox_id != second.inbox_id
