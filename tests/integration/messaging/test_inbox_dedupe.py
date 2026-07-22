"""Inbox deduplication integration tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from cps.domain.messaging.inbox import InboxReceiveDraft
from cps.domain.operations.inbox_handler import OperationInboxHandler
from cps.domain.operations.service import (
    EVENT_TYPE_LATE_RESULT,
    EVENT_TYPE_PROGRESS,
    OperationService,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import InboxProcessState, OperationState
from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.integration.db.seed_helpers import seed_operation_graph
from tests.integration.messaging.inbox_helpers import (
    CONSUMER_NAME,
    advance_operation_to_running,
    bind_fixture_to_operation,
    load_event_fixture,
    process_event_once,
)
from tests.integration.messaging.inbox_test_support import (
    InboxRaceCoordinator,
    race_process_message,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sequential_duplicate_produces_single_domain_effect(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )

    first_duplicate = await process_event_once(db_session_factory, fixture)
    second_duplicate = await process_event_once(db_session_factory, fixture)
    assert first_duplicate is False
    assert second_duplicate is True

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.consumer_name == CONSUMER_NAME,
                InboxMessage.message_id == message_id,
                InboxMessage.process_state == InboxProcessState.PROCESSED,
            )
        )
        progress_events = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_PROGRESS,
            )
        )
        operation = await session.get(Operation, operation_id)
    assert inbox_count == 1
    assert progress_events == 1
    assert operation is not None
    assert operation.progress_percent == 25


@pytest.mark.asyncio
async def test_different_consumer_name_processes_independently(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )

    await process_event_once(db_session_factory, fixture, consumer_name="consumer-a")
    await process_event_once(db_session_factory, fixture, consumer_name="consumer-b")

    async with db_session_factory() as session:
        inbox_count = await session.scalar(select(func.count()).select_from(InboxMessage))
    assert inbox_count == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_winner_commit(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )
    draft = InboxReceiveDraft(
        consumer_name=CONSUMER_NAME,
        message_id=message_id,
        message_type=fixture["message_type"],
        payload=fixture,
        received_at=datetime.fromisoformat(fixture["occurred_at"].replace("Z", "+00:00")),
    )
    coordinator = InboxRaceCoordinator(worker_count=2)
    outcomes = await asyncio.gather(
        race_process_message(
            db_session_factory=db_session_factory,
            coordinator=coordinator,
            draft=draft,
            fixture=fixture,
            should_fail=False,
        ),
        race_process_message(
            db_session_factory=db_session_factory,
            coordinator=coordinator,
            draft=draft,
            fixture=fixture,
            should_fail=False,
        ),
        return_exceptions=True,
    )
    processed = sum(1 for outcome in outcomes if outcome == "processed")
    duplicates = sum(1 for outcome in outcomes if outcome == "duplicate")
    assert processed == 1
    assert duplicates == 1

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.message_id == message_id,
                InboxMessage.process_state == InboxProcessState.PROCESSED,
            )
        )
        progress_events = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_PROGRESS,
            )
        )
    assert inbox_count == 1
    assert progress_events == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_winner_rollback(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )
    draft = InboxReceiveDraft(
        consumer_name=CONSUMER_NAME,
        message_id=message_id,
        message_type=fixture["message_type"],
        payload=fixture,
        received_at=datetime.fromisoformat(fixture["occurred_at"].replace("Z", "+00:00")),
    )
    rollback_done = asyncio.Event()

    async def failing_worker() -> str:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        try:
            async with uow:
                result = await uow.inbox.try_insert_received(draft)
                assert result.requires_processing
                raise RuntimeError("handler failed")
        except RuntimeError:
            rollback_done.set()
            return "rolled_back"
        return "unexpected"

    async def succeeding_worker() -> str:
        await rollback_done.wait()
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            result = await uow.inbox.try_insert_received(draft)
            assert result.requires_processing
            from cps.contracts.messages.envelope import MessageEnvelope

            handler = OperationInboxHandler(uow.operations)
            await handler.handle(MessageEnvelope.model_validate(fixture))
            assert result.inbox_id is not None
            await uow.inbox.mark_processed(result.inbox_id, now=datetime.now(UTC))
            await uow.commit()
        return "processed"

    outcomes = await asyncio.gather(failing_worker(), succeeding_worker())
    assert sorted(outcomes) == ["processed", "rolled_back"]

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.message_id == message_id,
                InboxMessage.process_state == InboxProcessState.PROCESSED,
            )
        )
    assert inbox_count == 1


@pytest.mark.asyncio
async def test_crash_before_commit_leaves_no_inbox_row(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(RuntimeError, match="crash"):
        async with uow:
            draft = InboxReceiveDraft(
                consumer_name=CONSUMER_NAME,
                message_id=message_id,
                message_type=fixture["message_type"],
                payload=fixture,
                received_at=datetime.fromisoformat(fixture["occurred_at"].replace("Z", "+00:00")),
            )
            await uow.inbox.try_insert_received(draft)
            raise RuntimeError("crash before commit")

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.message_id == message_id,
            )
        )
    assert inbox_count == 0

    duplicate = await process_event_once(db_session_factory, fixture)
    assert duplicate is False

    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(
                InboxMessage.message_id == message_id,
                InboxMessage.process_state == InboxProcessState.PROCESSED,
            )
        )
    assert inbox_count == 1


@pytest.mark.asyncio
async def test_crash_after_commit_before_ack_is_duplicate_on_redelivery(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )

    await process_event_once(db_session_factory, fixture)
    duplicate = await process_event_once(db_session_factory, fixture)
    assert duplicate is True

    async with db_session_factory() as session:
        progress_events = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_PROGRESS,
            )
        )
    assert progress_events == 1


@pytest.mark.asyncio
async def test_inbox_row_id_is_uuidv7(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    await advance_operation_to_running(operation_id, db_session_factory)
    message_id = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )
    await process_event_once(db_session_factory, fixture)

    async with db_session_factory() as session:
        row = await session.scalar(
            select(InboxMessage).where(InboxMessage.message_id == message_id)
        )
    assert row is not None
    assert row.id.version == 7
    assert row.message_id == message_id


@pytest.mark.asyncio
async def test_late_completed_event_on_terminal_operation(
    db_tx,
    db_session_factory,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    operation_id = graph["operation_id"]
    version = await advance_operation_to_running(operation_id, db_session_factory)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=version,
            to_state=OperationState.SUCCEEDED,
        )
        await uow.commit()

    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_completed.json"),
        operation_id=operation_id,
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    await process_event_once(db_session_factory, fixture)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        late_events = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_LATE_RESULT,
            )
        )
    assert operation is not None
    assert operation.state is OperationState.SUCCEEDED
    assert late_events == 1

    duplicate = await process_event_once(db_session_factory, fixture)
    assert duplicate is True

    async with db_session_factory() as session:
        late_events = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == operation_id,
                OperationEvent.event_type == EVENT_TYPE_LATE_RESULT,
            )
        )
    assert late_events == 1
