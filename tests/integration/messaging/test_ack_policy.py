"""Live RabbitMQ ack-policy matrix for CPS inbox consumer."""

from __future__ import annotations

import asyncio
import json
import uuid

import aio_pika
import pytest
from sqlalchemy import func, select

from cps.domain.operations.errors import OperationPersistenceError
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.messaging.constants import ROUTING_KEY_CLOUD_OPERATION_RETRY
from cps.infrastructure.messaging.inbox_consumer import DeliveryProcessingRecord
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from tests.integration.db.seed_helpers import insert_provider, seed_operation_graph
from tests.integration.messaging.ack_policy_support import (
    IncomingAdapter,
    assert_exactly_one_terminal_action,
    build_consumer,
    process_queue_message,
    publish_event,
    take_dlq_message,
)
from tests.integration.messaging.inbox_helpers import (
    advance_operation_to_running,
    bind_fixture_to_operation,
    delivery_headers,
    load_event_fixture,
)

pytestmark = pytest.mark.integration


async def _seed_running_operation(db_tx, db_session_factory):
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    await advance_operation_to_running(graph["operation_id"], db_session_factory)
    return graph


@pytest.mark.asyncio
async def test_valid_progress_commit_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.completed is True
    assert outcome.record.committed is True
    await assert_exactly_one_terminal_action(outcome.record)


@pytest.mark.asyncio
async def test_valid_completed_terminal_success_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_completed.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.completed"
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.committed is True
    async with db_session_factory() as session:
        operation = await session.get(Operation, graph["operation_id"])
    assert operation is not None
    assert operation.state is OperationState.SUCCEEDED


@pytest.mark.asyncio
async def test_valid_failed_terminal_error_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_failed.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.failed"
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.committed is True
    async with db_session_factory() as session:
        operation = await session.get(Operation, graph["operation_id"])
    assert operation is not None
    assert operation.state is OperationState.FAILED
    assert operation.error_payload is not None


@pytest.mark.asyncio
async def test_sequential_duplicate_handler_once_both_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    message_id = new_uuid7()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=message_id,
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    for _ in range(2):
        await publish_event(
            declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
        )
        outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
        assert outcome.record.acked is True
    async with db_session_factory() as session:
        progress_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == graph["operation_id"],
                OperationEvent.event_type == "PROGRESS",
            )
        )
    assert progress_count == 1


@pytest.mark.asyncio
async def test_retry_attempt_1_publish_confirm_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )

    async def fail_once(*args, **kwargs):
        raise OperationPersistenceError("transient")

    monkeypatch.setattr(consumer, "_process_inbox", fail_once)
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    incoming = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(IncomingAdapter(incoming), record)
    assert record.retry_published is True
    assert record.acked is True
    retry_message = await declared_event_topology.retry_queues[0].get(timeout=2, fail=False)
    assert retry_message is not None
    await retry_message.ack()


@pytest.mark.asyncio
async def test_retry_attempt_2_publish_confirm_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )

    async def fail_once(*args, **kwargs):
        raise OperationPersistenceError("transient")

    monkeypatch.setattr(consumer, "_process_inbox", fail_once)
    body = json.dumps(fixture).encode()
    headers = delivery_headers(
        message_id=uuid.UUID(fixture["message_id"]),
        correlation_id=uuid.UUID(fixture["correlation_id"]),
        attempt=2,
    )
    headers["x-original-routing-key"] = "cloud.operation.progress"
    headers["x-retry-reason"] = "INBOX_HANDLER_ERROR"
    await declared_event_topology.event_exchange.publish(
        aio_pika.Message(
            body=body, headers=headers, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        ),
        routing_key=ROUTING_KEY_CLOUD_OPERATION_RETRY,
    )
    incoming = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(IncomingAdapter(incoming), record)
    assert record.retry_published is True
    assert record.acked is True
    retry_message = await declared_event_topology.retry_queues[1].get(timeout=2, fail=False)
    assert retry_message is not None
    await retry_message.ack()


@pytest.mark.asyncio
async def test_exhausted_attempt_rejects_to_dlq_once(
    db_tx,
    db_session_factory,
    declared_event_topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )

    async def fail_once(*args, **kwargs):
        raise OperationPersistenceError("transient")

    monkeypatch.setattr(consumer, "_process_inbox", fail_once)
    await publish_event(
        declared_event_topology,
        fixture=fixture,
        routing_key="cloud.operation.progress",
        attempt=3,
        extra_headers={
            "x-original-routing-key": "cloud.operation.progress",
            "x-retry-reason": "INBOX_HANDLER_ERROR",
        },
    )
    incoming = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    await consumer.process_delivery(IncomingAdapter(incoming), record)
    assert record.rejected is True
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()


@pytest.mark.asyncio
async def test_malformed_json_dlq_once_no_db_row(
    db_session_factory,
    declared_event_topology,
) -> None:
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await declared_event_topology.event_exchange.publish(
        aio_pika.Message(body=b"not-json", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
        routing_key="cloud.operation.progress",
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()
    async with db_session_factory() as session:
        inbox_count = await session.scalar(select(func.count()).select_from(InboxMessage))
    assert inbox_count == 0


@pytest.mark.asyncio
async def test_unsupported_major_dlq_once(
    db_session_factory,
    declared_event_topology,
) -> None:
    payload = load_event_fixture("operation_progress.json")
    payload["schema_version"] = "2.0"
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology, fixture=payload, routing_key="cloud.operation.progress"
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()


@pytest.mark.asyncio
async def test_unknown_type_dlq_once(
    db_session_factory,
    declared_event_topology,
) -> None:
    payload = load_event_fixture("operation_progress.json")
    payload["message_type"] = "cloud.operation.unknown"
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology, fixture=payload, routing_key="cloud.operation.unknown"
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()


@pytest.mark.asyncio
async def test_routing_key_message_type_mismatch_dlq_once(
    db_session_factory,
    declared_event_topology,
) -> None:
    payload = load_event_fixture("operation_completed.json")
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology,
        fixture=payload,
        routing_key="cloud.operation.progress",
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    assert outcome.record.committed is False
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()


@pytest.mark.asyncio
async def test_ownership_mismatch_dlq_once_no_mutation(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = seed_operation_graph(db_tx)
    db_tx.commit()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=new_uuid7(),
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    assert outcome.record.retry_published is False
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()
    async with db_session_factory() as session:
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxMessage)
            .where(InboxMessage.message_id == uuid.UUID(fixture["message_id"]))
        )
        event_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == graph["operation_id"])
        )
        operation = await session.get(Operation, graph["operation_id"])
    assert inbox_count == 0
    assert event_count == 0
    assert operation is not None
    assert operation.version == 1


@pytest.mark.asyncio
async def test_wrong_provider_id_ownership_mismatch(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = seed_operation_graph(db_tx)
    other_provider = insert_provider(db_tx)
    db_tx.commit()
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=other_provider,
        provider_connection_id=graph["connection_id"],
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.rejected is True
    dlq_message = await take_dlq_message(declared_event_topology.dlq_queue)
    await dlq_message.ack()


@pytest.mark.asyncio
async def test_late_completed_after_terminal_ack(
    db_tx,
    db_session_factory,
    declared_event_topology,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    completed = bind_fixture_to_operation(
        load_event_fixture("operation_completed.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    consumer = build_consumer(
        db_session_factory=db_session_factory, topology=declared_event_topology
    )
    await publish_event(
        declared_event_topology, fixture=completed, routing_key="cloud.operation.completed"
    )
    await process_queue_message(consumer, declared_event_topology.event_queue)

    late_failed = bind_fixture_to_operation(
        load_event_fixture("operation_failed.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
        message_id=new_uuid7(),
    )
    await publish_event(
        declared_event_topology, fixture=late_failed, routing_key="cloud.operation.failed"
    )
    outcome = await process_queue_message(consumer, declared_event_topology.event_queue)
    assert outcome.record.committed is True
    async with db_session_factory() as session:
        late_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(
                OperationEvent.operation_id == graph["operation_id"],
                OperationEvent.event_type == "LATE_RESULT",
            )
        )
    assert late_count == 1


@pytest.mark.asyncio
async def test_shutdown_grace_timeout_redelivers_original(
    db_tx,
    db_session_factory,
    declared_event_topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    lifecycle = WorkerLifecycle()
    consumer = build_consumer(
        db_session_factory=db_session_factory,
        topology=declared_event_topology,
        lifecycle=lifecycle,
    )
    blocked = asyncio.Event()

    async def slow_process(*args, **kwargs):
        await blocked.wait()
        from cps.domain.messaging.inbox import InboxProcessOutcome

        return InboxProcessOutcome(duplicate=False, committed=True)

    monkeypatch.setattr(consumer, "_process_inbox", slow_process)
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    incoming = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    processing = asyncio.create_task(consumer.process_delivery(IncomingAdapter(incoming), record))
    await asyncio.sleep(0.05)
    lifecycle.begin_shutdown()
    await asyncio.sleep(0.2)
    assert record.acked is False
    processing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await processing
    await incoming.reject(requeue=True)
    redelivered = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert redelivered is not None
    await redelivered.ack()


@pytest.mark.asyncio
async def test_shutdown_grace_acks_in_flight_delivery_that_commits(
    db_tx,
    db_session_factory,
    declared_event_topology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_running_operation(db_tx, db_session_factory)
    fixture = bind_fixture_to_operation(
        load_event_fixture("operation_progress.json"),
        operation_id=graph["operation_id"],
        provider_id=graph["provider_id"],
        provider_connection_id=graph["connection_id"],
    )
    lifecycle = WorkerLifecycle()
    consumer = build_consumer(
        db_session_factory=db_session_factory,
        topology=declared_event_topology,
        lifecycle=lifecycle,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    process_inbox = consumer._process_inbox

    async def controlled_process(*args, **kwargs):
        started.set()
        await release.wait()
        return await process_inbox(*args, **kwargs)

    monkeypatch.setattr(consumer, "_process_inbox", controlled_process)
    await publish_event(
        declared_event_topology, fixture=fixture, routing_key="cloud.operation.progress"
    )
    incoming = await declared_event_topology.event_queue.get(timeout=5, fail=False)
    assert incoming is not None
    record = DeliveryProcessingRecord()
    processing = asyncio.create_task(consumer.process_delivery(IncomingAdapter(incoming), record))
    await asyncio.wait_for(started.wait(), timeout=2)

    lifecycle.begin_shutdown()
    release.set()
    await asyncio.wait_for(processing, timeout=5)

    assert record.committed is True
    assert record.acked is True
    assert record.terminal_action_count == 1
    assert await declared_event_topology.event_queue.get(timeout=0.25, fail=False) is None
