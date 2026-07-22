"""Transactional outbox repository integration coverage."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import aio_pika
import pytest
from sqlalchemy import select

from cps.contracts.messages.delivery import parse_delivery_metadata
from cps.contracts.messages.envelope import MessageEnvelope
from cps.domain.messaging.outbox import OutboxDraft
from cps.domain.operations.create import create_operation_idempotent
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OutboxPublishState
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.outbox_messages import OutboxMessage
from cps.infrastructure.db.repositories.outbox import OutboxPersistenceError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.infrastructure.messaging.outbox_publisher import OutboxPublisher
from tests.integration.db.seed_helpers import seed_operation_graph

pytestmark = pytest.mark.integration


@pytest.fixture
def rabbitmq_url() -> str:
    value = os.getenv("CPS_TEST_RABBITMQ_URL")
    if not value:
        pytest.fail("CPS_TEST_RABBITMQ_URL is required when integration is enabled")
    return value


def _draft(operation_id, *, message_id=None) -> OutboxDraft:
    now = datetime.now(UTC)
    message_id = message_id or new_uuid7()
    correlation_id = new_uuid7()
    return OutboxDraft(
        aggregate_type="operation",
        aggregate_id=operation_id,
        message_id=message_id,
        message_type="openstack.connection.validate",
        routing_key="openstack.connection.validate",
        payload={
            "message_id": str(message_id),
            "message_type": "openstack.connection.validate",
            "schema_version": "1.0",
            "occurred_at": now.isoformat(),
            "correlation_id": str(correlation_id),
            "operation_id": str(operation_id),
            "provider_id": str(new_uuid7()),
            "provider_connection_id": str(new_uuid7()),
            "trace_context": {},
            "payload": {},
        },
        correlation_id=correlation_id,
        occurred_at=now,
    )


@pytest.mark.asyncio
async def test_operation_and_outbox_insert_commit_atomically(
    db_admin_conn,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_admin_conn)
    db_admin_conn.commit()
    operation_id = new_uuid7()
    correlation_id = new_uuid7()
    draft = _draft(operation_id)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await create_operation_idempotent(
            uow.operations,
            provider_connection_id=graph["connection_id"],
            operation_type="openstack.connection.validate",
            request_payload={"safe": "test"},
            correlation_id=correlation_id,
            operation_id=operation_id,
            outbox_repository=uow.outbox,
            outbox_draft=draft,
        )
        await uow.commit()

    async with db_session_factory() as session:
        assert await session.get(Operation, operation_id) is not None
        stored = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert stored is not None
        assert stored.message_id == draft.message_id


@pytest.mark.asyncio
async def test_operation_and_outbox_insert_rollback_atomically(
    db_admin_conn,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_admin_conn)
    db_admin_conn.commit()
    operation_id = new_uuid7()
    draft = _draft(operation_id)

    with pytest.raises(RuntimeError, match="rollback"):
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await create_operation_idempotent(
                uow.operations,
                provider_connection_id=graph["connection_id"],
                operation_type="openstack.connection.validate",
                request_payload={"safe": "test"},
                correlation_id=new_uuid7(),
                operation_id=operation_id,
                outbox_repository=uow.outbox,
                outbox_draft=draft,
            )
            raise RuntimeError("rollback")

    async with db_session_factory() as session:
        assert await session.get(Operation, operation_id) is None
        assert (
            await session.scalar(
                select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
            )
            is None
        )


@pytest.mark.asyncio
async def test_cps_created_operation_id_is_uuidv7(
    db_admin_conn,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_admin_conn)
    db_admin_conn.commit()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        operation = await create_operation_idempotent(
            uow.operations,
            provider_connection_id=graph["connection_id"],
            operation_type="openstack.connection.validate",
            request_payload={"safe": "test"},
            correlation_id=new_uuid7(),
        )
        await uow.commit()

    assert operation.id.version == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("max_attempts", [2, 4])
async def test_repository_rejects_noncanonical_max_attempts(
    db_session_factory,
    max_attempts: int,
) -> None:
    draft = _draft(new_uuid7())
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        await uow.outbox.add(draft)
        await uow.commit()

    claim_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with claim_uow:
        with pytest.raises(OutboxPersistenceError, match="canonical default"):
            await claim_uow.outbox.claim_due(
                claimed_by="publisher",
                batch_size=1,
                now=datetime.now(UTC),
                max_attempts=max_attempts,
            )


@pytest.mark.asyncio
async def test_two_workers_claim_disjoint_rows_and_expired_lease_is_reclaimable(
    db_session_factory,
) -> None:
    drafts = [_draft(new_uuid7()) for _ in range(3)]
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        for draft in drafts:
            await uow.outbox.add(draft)
        await uow.commit()
    now = datetime.now(UTC)

    async def claim(owner: str):
        claim_uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with claim_uow:
            rows = await claim_uow.outbox.claim_due(
                claimed_by=owner,
                batch_size=2,
                now=now,
                max_attempts=3,
            )
            await claim_uow.commit()
            return rows

    first, second = await asyncio.gather(claim("publisher-a"), claim("publisher-b"))
    claimed_ids = {item.claim.row_id for item in first} | {item.claim.row_id for item in second}
    assert not ({item.claim.row_id for item in first} & {item.claim.row_id for item in second})
    assert len(claimed_ids) == 3
    assert all(item.claim.row_id.version == 7 for item in (*first, *second))
    assert all(item.claim.claim_token.version == 4 for item in (*first, *second))

    first_message = first[0]
    active_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with active_uow:
        assert not await active_uow.outbox.claim_due(
            claimed_by="publisher-c",
            batch_size=3,
            now=now + timedelta(seconds=1),
            max_attempts=3,
        )
        await active_uow.commit()

    reclaim_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with reclaim_uow:
        reclaimed = await reclaim_uow.outbox.claim_due(
            claimed_by="publisher-c",
            batch_size=3,
            now=first_message.claim_expires_at + timedelta(seconds=1),
            max_attempts=3,
        )
        await reclaim_uow.commit()
    matching = next(item for item in reclaimed if item.claim.row_id == first_message.claim.row_id)
    assert matching.claim.claim_token != first_message.claim.claim_token
    assert matching.claim.claim_token.version == 4
    assert matching.attempt_count == 2


@pytest.mark.asyncio
async def test_stale_finalize_cannot_overwrite_reclaimed_lease(
    db_session_factory,
) -> None:
    now = datetime.now(UTC)
    draft = _draft(new_uuid7())
    insert_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with insert_uow:
        await insert_uow.outbox.add(draft)
        await insert_uow.commit()

    first_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with first_uow:
        first = (
            await first_uow.outbox.claim_due(
                claimed_by="publisher-a", batch_size=1, now=now, max_attempts=3
            )
        )[0]
        await first_uow.commit()
    second_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with second_uow:
        second = (
            await second_uow.outbox.claim_due(
                claimed_by="publisher-b",
                batch_size=1,
                now=first.claim_expires_at + timedelta(seconds=1),
                max_attempts=3,
            )
        )[0]
        await second_uow.commit()
    stale_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with stale_uow:
        stale = await stale_uow.outbox.mark_published(first.claim, now=datetime.now(UTC))
        await stale_uow.commit()
    assert stale.stale and not stale.finalized

    winner_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with winner_uow:
        winner = await winner_uow.outbox.mark_published(second.claim, now=datetime.now(UTC))
        await winner_uow.commit()
    assert winner.finalized
    async with db_session_factory() as session:
        row = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert row is not None
        assert row.publish_state is OutboxPublishState.PUBLISHED


@pytest.mark.asyncio
async def test_live_publish_confirm_finalizes_and_preserves_message_id(
    db_session_factory,
    rabbitmq_url: str,
) -> None:
    draft = _draft(new_uuid7())
    insert_uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with insert_uow:
        await insert_uow.outbox.add(draft)
        await insert_uow.commit()

    connection = await aio_pika.connect_robust(rabbitmq_url, timeout=10)
    queue = None
    try:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "cmp.cloud.command.v1", aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(
            f"cps.test.outbox.{new_uuid7().hex}", durable=False, auto_delete=True
        )
        await queue.bind(exchange, "openstack.connection.validate")
        publisher = OutboxPublisher(
            session_factory=db_session_factory,
            rabbitmq_url=rabbitmq_url,
            publisher_id="cps-integration-publisher",
        )

        assert await publisher.publish_due(batch_size=1) == 1
        received = await queue.get(timeout=10, fail=True)
        envelope = MessageEnvelope.model_validate_json(received.body)
        metadata = parse_delivery_metadata(received.headers or {})
        assert envelope.message_id == draft.message_id
        assert envelope.correlation_id == draft.correlation_id
        assert metadata.message_id == draft.message_id
        assert metadata.correlation_id == draft.correlation_id
        assert received.message_id == str(draft.message_id)
        assert received.correlation_id == str(draft.correlation_id)
        assert metadata.attempt == 1
        await received.ack()
    finally:
        if queue is not None:
            await queue.delete(if_unused=False, if_empty=False)
        await connection.close()

    async with db_session_factory() as session:
        row = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.message_id == draft.message_id)
        )
        assert row is not None
        assert row.publish_state is OutboxPublishState.PUBLISHED
        assert row.message_id == draft.message_id
        assert row.payload["correlation_id"] == str(draft.correlation_id)
        assert row.claimed_by is None
        assert row.claim_token is None
