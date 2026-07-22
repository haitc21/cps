"""Publisher-boundary crash recovery for the transactional outbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import aio_pika
import pytest
from pamqp.commands import Basic
from sqlalchemy import select

from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OutboxPublishState
from cps.infrastructure.db.models.outbox_messages import OutboxMessage
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.infrastructure.messaging.outbox_publisher import OutboxPublisher, PublishConfirmError
from tests.integration.messaging.test_outbox_publish import _draft

pytestmark = pytest.mark.integration


class _AckExchange:
    def __init__(self) -> None:
        self.records: list[tuple[aio_pika.Message, str]] = []

    async def publish(
        self, message: aio_pika.Message, *, routing_key: str, **kwargs: object
    ) -> Basic.Ack:
        self.records.append((message, routing_key))
        return Basic.Ack(delivery_tag=len(self.records))


class _Channel:
    def __init__(self, exchange: _AckExchange) -> None:
        self._exchange = exchange

    async def declare_exchange(self, *args: object, **kwargs: object) -> _AckExchange:
        return self._exchange

    async def close(self) -> None:
        return None


class _Connection:
    def __init__(self, exchange: _AckExchange) -> None:
        self._channel = _Channel(exchange)

    async def channel(self, **kwargs: object) -> _Channel:
        return self._channel

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_confirm_finalize_failure_reclaims_and_republishes_same_message_id(
    db_session_factory,
) -> None:
    draft = _draft(new_uuid7())
    claim_now = datetime.now(UTC)
    insert_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with insert_uow:
        await insert_uow.outbox.add(draft)
        await insert_uow.commit()

    exchange = _AckExchange()
    first = OutboxPublisher(
        session_factory=db_session_factory,
        rabbitmq_url="amqp://redacted",
        publisher_id="publisher-a",
        connect=lambda *args, **kwargs: _return(_Connection(exchange)),
    )
    first_claims = []

    async def fail_finalize(message):
        first_claims.append(message)
        raise PublishConfirmError("FINALIZE_FAILURE")

    first._record_success = fail_finalize  # type: ignore[method-assign]
    with pytest.raises(PublishConfirmError, match="FINALIZE_FAILURE"):
        await first.publish_due(batch_size=1, now=claim_now)

    async with db_session_factory() as session:
        row = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert row is not None
        assert row.publish_state is OutboxPublishState.CLAIMED
        first_expiry = row.claim_expires_at
        assert first_expiry is not None

    second = OutboxPublisher(
        session_factory=db_session_factory,
        rabbitmq_url="amqp://redacted",
        publisher_id="publisher-b",
        connect=lambda *args, **kwargs: _return(_Connection(exchange)),
    )
    assert await second.publish_due(batch_size=1, now=claim_now + timedelta(seconds=1)) == 0
    second_claims = []
    original_success = second._record_success

    async def record_success(message):
        second_claims.append(message)
        return await original_success(message)

    second._record_success = record_success  # type: ignore[method-assign]
    finalized = await second.publish_due(batch_size=1, now=datetime.now(UTC) + timedelta(hours=1))
    async with db_session_factory() as session:
        after_second = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert after_second is not None
        assert after_second.attempt_count == 2
        assert len(exchange.records) == 2
        assert after_second.last_error is None
        assert after_second.publish_state is OutboxPublishState.PUBLISHED
    assert finalized == 1

    assert len(exchange.records) == 2
    first_message, _ = exchange.records[0]
    second_message, _ = exchange.records[1]
    first_envelope = json.loads(first_message.body)
    second_envelope = json.loads(second_message.body)
    assert first_envelope["message_id"] == second_envelope["message_id"] == str(draft.message_id)
    assert first_message.message_id == second_message.message_id == str(draft.message_id)
    assert (
        first_message.headers["x-message-id"]
        == second_message.headers["x-message-id"]
        == str(draft.message_id)
    )
    assert first_message.correlation_id == second_message.correlation_id
    assert first_message.headers["x-attempt"] == 1
    assert second_message.headers["x-attempt"] == 2
    assert first_claims[0].claim.claim_token != second_claims[0].claim.claim_token

    async with db_session_factory() as session:
        row = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert row is not None
        assert row.publish_state is OutboxPublishState.PUBLISHED
        assert row.claimed_by is None
        assert row.claim_token is None
        assert row.claim_expires_at is None


async def _return(value):
    return value
