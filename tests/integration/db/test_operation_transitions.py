"""CPS-104 Task 4: operation transition integration tests."""

from __future__ import annotations

import asyncio
import inspect
import traceback
import uuid

import psycopg
import pytest
from sqlalchemy import func, select

from cps.domain.operations.errors import (
    ConcurrentUpdateError,
    InvalidOperationTransitionError,
    InvalidProgressStateError,
    InvalidProgressValueError,
    OperationNotFoundError,
    OperationPersistenceError,
    UnsafeEventDetailsError,
)
from cps.domain.operations.event_details import SafeEventDetails
from cps.domain.operations.service import (
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STATE_CHANGED,
    OperationService,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OperationState
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.repositories.operations import OperationRepository
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.integration.db.seed_helpers import seed_operation_graph

pytestmark = pytest.mark.integration

_SECRET_DETAIL = "super-sensitive-detail-value"  # pragma: allowlist secret


def _assert_redacted_public_exception(exc: BaseException) -> None:
    rendered = str(exc) + repr(exc)
    forbidden = (
        "INSERT",
        "SELECT",
        "UPDATE",
        "DELETE",
        "postgresql",
        "psycopg",
        "DETAIL:",
        "constraint",
        _SECRET_DETAIL,
    )
    for fragment in forbidden:
        assert fragment not in rendered
    assert exc.__cause__ is None


async def _advance_operation_to_running(
    operation_id: uuid.UUID,
    db_session_factory,
) -> int:
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


async def _advance_operation_to_terminal(
    operation_id: uuid.UUID,
    db_session_factory,
    terminal: OperationState,
) -> int:
    version = await _advance_operation_to_running(operation_id, db_session_factory)
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        if terminal is OperationState.SUCCEEDED:
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=version,
                to_state=OperationState.SUCCEEDED,
            )
        elif terminal is OperationState.FAILED:
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=version,
                to_state=OperationState.FAILED,
            )
        else:
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=version,
                to_state=OperationState.TIMED_OUT,
            )
        await uow.commit()
    return version + 1


async def _seed_accepted_operation(db_tx: psycopg.Connection, db_session_factory):
    ids = seed_operation_graph(db_tx)
    db_tx.commit()
    return ids["operation_id"], db_session_factory


@pytest.mark.asyncio
async def test_transition_appends_state_changed_event_with_sequence_one(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
        )
        await uow.commit()

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == OperationState.QUEUED
        assert operation.version == 2

        events = (
            (
                await session.execute(
                    select(OperationEvent)
                    .where(OperationEvent.operation_id == operation_id)
                    .order_by(OperationEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].sequence == 1
        assert events[0].event_type == EVENT_TYPE_STATE_CHANGED
        assert events[0].from_state == OperationState.ACCEPTED
        assert events[0].to_state == OperationState.QUEUED
        assert events[0].id.version == 7


@pytest.mark.asyncio
async def test_progress_records_event_without_state_change(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

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
        await service.record_progress(
            operation_id=operation_id,
            expected_version=3,
            progress_percent=42,
            details={"phase": "validate"},
        )
        await uow.commit()

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == OperationState.RUNNING
        assert operation.progress_percent == 42
        assert operation.version == 4

        events = (
            (
                await session.execute(
                    select(OperationEvent)
                    .where(OperationEvent.operation_id == operation_id)
                    .order_by(OperationEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert [event.sequence for event in events] == [1, 2, 3]
        assert events[2].event_type == EVENT_TYPE_PROGRESS
        assert events[2].from_state is None
        assert events[2].to_state is None


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected_without_persisting_event(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(InvalidOperationTransitionError):
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=1,
                to_state=OperationState.RUNNING,
            )

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == OperationState.ACCEPTED
        assert operation.version == 1
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_stale_version_raises_concurrent_update_error(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
        )
        await uow.commit()

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(ConcurrentUpdateError, match="concurrent update"):
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=1,
                to_state=OperationState.RUNNING,
            )


@pytest.mark.asyncio
async def test_concurrent_transitions_one_wins_one_conflicts(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    barrier = asyncio.Barrier(2)

    async def attempt_transition() -> None:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await barrier.wait()
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=1,
                to_state=OperationState.QUEUED,
            )
            await uow.commit()

    results = await asyncio.gather(
        attempt_transition(), attempt_transition(), return_exceptions=True
    )
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentUpdateError)
    assert "IntegrityError" not in type(errors[0]).__name__
    assert "IntegrityError" not in str(errors[0])

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == OperationState.QUEUED
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_transition_and_progress_race_produce_monotonic_sequences(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

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

    barrier = asyncio.Barrier(2)

    async def transition_to_waiting() -> None:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await barrier.wait()
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=3,
                to_state=OperationState.WAITING_PROVIDER,
            )
            await uow.commit()

    async def record_progress_update() -> None:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await barrier.wait()
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=3,
                progress_percent=75,
            )
            await uow.commit()

    results = await asyncio.gather(
        transition_to_waiting(),
        record_progress_update(),
        return_exceptions=True,
    )
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentUpdateError)

    async with db_session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OperationEvent)
                    .where(OperationEvent.operation_id == operation_id)
                    .order_by(OperationEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert [event.sequence for event in events] == [1, 2, 3]
        assert events[0].event_type == EVENT_TYPE_STATE_CHANGED
        assert events[1].event_type == EVENT_TYPE_STATE_CHANGED
        assert events[2].event_type in {EVENT_TYPE_STATE_CHANGED, EVENT_TYPE_PROGRESS}


@pytest.mark.asyncio
async def test_updated_at_advances_on_successful_mutation(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    async with db_session_factory() as session:
        before = (await session.get(Operation, operation_id)).updated_at

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
        )
        await uow.commit()

    async with db_session_factory() as session:
        after = (await session.get(Operation, operation_id)).updated_at
        assert after > before


@pytest.mark.asyncio
async def test_rollback_discards_operation_and_event_changes(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(RuntimeError, match="force rollback"):
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=1,
                to_state=OperationState.QUEUED,
            )
            raise RuntimeError("force rollback")

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == OperationState.ACCEPTED
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_progress_rejected_outside_running_or_waiting(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(InvalidProgressStateError):
        async with uow:
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=1,
                progress_percent=10,
            )


@pytest.mark.asyncio
async def test_operation_repository_has_append_only_event_api() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(OperationRepository, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert "apply_state_transition" in public_methods
    assert "apply_progress_update" in public_methods
    assert "get_events" in public_methods
    assert "delete_operation" not in public_methods
    assert "delete_event" not in public_methods
    assert "update_event" not in public_methods


@pytest.mark.asyncio
async def test_operation_with_history_cannot_be_deleted(
    migrated_database: str,
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
        )
        await uow.commit()

    conninfo = migrated_database.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.RestrictViolation):
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM operations WHERE id = %s", (operation_id,))


@pytest.mark.asyncio
async def test_transition_rejects_unsafe_event_details(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed") as exc_info:
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=1,
                to_state=OperationState.QUEUED,
                details={"password": _SECRET_DETAIL},
            )
    _assert_redacted_public_exception(exc_info.value)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.version == 1
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_repository_rejects_forged_safe_event_details_without_persisting_secret(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        before_version = operation.version

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(UnsafeEventDetailsError, match="event details are not allowed") as exc_info:
        async with uow:
            repo = uow.operations
            locked = await repo.lock_operation(operation_id)
            assert locked is not None
            forged = object.__new__(SafeEventDetails)
            object.__setattr__(forged, "_payload", {"password": _SECRET_DETAIL})
            object.__setattr__(forged, "_validation_token", object())
            await repo.apply_state_transition(
                operation=locked,
                expected_version=before_version,
                to_state=OperationState.QUEUED,
                event_id=new_uuid7(),
                event_type=EVENT_TYPE_STATE_CHANGED,
                details=forged,
                message_id=None,
                from_state=OperationState.ACCEPTED,
            )
    _assert_redacted_public_exception(exc_info.value)
    assert _SECRET_DETAIL not in traceback.format_exc()

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.version == before_version
        assert operation.state == OperationState.ACCEPTED
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 0


@pytest.mark.asyncio
async def test_progress_rejects_unsafe_event_details(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_running(operation_id, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(UnsafeEventDetailsError):
        async with uow:
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=version,
                progress_percent=10,
                details={"token": _SECRET_DETAIL},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_value", [-1, 101, True, "50", 42.5])
async def test_invalid_progress_rejected_before_persistence(
    db_tx: psycopg.Connection,
    db_session_factory,
    invalid_value: object,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_running(operation_id, db_session_factory)

    async with db_session_factory() as session:
        before = await session.get(Operation, operation_id)
        assert before is not None
        before_version = before.version
        before_updated_at = before.updated_at
        before_progress = before.progress_percent

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(
        InvalidProgressValueError, match="progress value is not allowed"
    ) as exc_info:
        async with uow:
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=version,
                progress_percent=invalid_value,  # type: ignore[arg-type]
            )
    _assert_redacted_public_exception(exc_info.value)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.version == before_version
        assert operation.updated_at == before_updated_at
        assert operation.progress_percent == before_progress
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_missing_operation_transition_raises_not_found(db_session_factory) -> None:
    missing_id = new_uuid7()
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(OperationNotFoundError, match="operation not found"):
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=missing_id,
                expected_version=1,
                to_state=OperationState.QUEUED,
            )


@pytest.mark.asyncio
async def test_missing_operation_progress_raises_not_found(db_session_factory) -> None:
    missing_id = new_uuid7()
    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(OperationNotFoundError, match="operation not found"):
        async with uow:
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=missing_id,
                expected_version=1,
                progress_percent=10,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [OperationState.SUCCEEDED, OperationState.FAILED, OperationState.TIMED_OUT],
)
async def test_terminal_operation_rejects_all_transitions(
    db_tx: psycopg.Connection,
    db_session_factory,
    terminal: OperationState,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_terminal(operation_id, db_session_factory, terminal)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(InvalidOperationTransitionError):
        async with uow:
            service = OperationService(uow.operations)
            await service.transition_operation(
                operation_id=operation_id,
                expected_version=version,
                to_state=OperationState.QUEUED,
            )

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.state == terminal
        assert operation.version == version
        before_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )

    async with db_session_factory() as session:
        after_count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert after_count == before_count


@pytest.mark.asyncio
async def test_concurrent_progress_updates_one_wins_one_conflicts(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_running(operation_id, db_session_factory)
    barrier = asyncio.Barrier(2)

    async def record_progress(percent: int) -> None:
        uow = SqlAlchemyUnitOfWork(db_session_factory)
        async with uow:
            await barrier.wait()
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=version,
                progress_percent=percent,
            )
            await uow.commit()

    results = await asyncio.wait_for(
        asyncio.gather(record_progress(25), record_progress(50), return_exceptions=True),
        timeout=10,
    )
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentUpdateError)

    async with db_session_factory() as session:
        operation = await session.get(Operation, operation_id)
        assert operation is not None
        assert operation.progress_percent in {25, 50}
        events = (
            (
                await session.execute(
                    select(OperationEvent)
                    .where(OperationEvent.operation_id == operation_id)
                    .order_by(OperationEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert [event.sequence for event in events] == [1, 2, 3]
        assert events[-1].event_type == EVENT_TYPE_PROGRESS


@pytest.mark.asyncio
async def test_event_details_deep_copy_isolated_from_caller_mutation(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    details = {"phase": "validate", "nested": {"step": 1}}

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
            details=details,
        )
        details["phase"] = "mutated"
        details["nested"]["step"] = 99
        await uow.commit()

    async with db_session_factory() as session:
        event = await session.scalar(
            select(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
            .order_by(OperationEvent.sequence)
            .limit(1)
        )
        assert event is not None
        assert event.details == {"phase": "validate", "nested": {"step": 1}}


@pytest.mark.asyncio
async def test_event_history_is_ordered_ascending(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_running(operation_id, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.record_progress(
            operation_id=operation_id,
            expected_version=version,
            progress_percent=10,
        )
        await uow.commit()

    async with db_session_factory() as session:
        repo = OperationRepository(session)
        events = await repo.get_events(operation_id)
        assert [event.sequence for event in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_invalid_progress_rollback_leaves_no_event(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)
    version = await _advance_operation_to_running(operation_id, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    with pytest.raises(InvalidProgressValueError):
        async with uow:
            service = OperationService(uow.operations)
            await service.record_progress(
                operation_id=operation_id,
                expected_version=version,
                progress_percent=-1,
            )

    async with db_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(OperationEvent)
            .where(OperationEvent.operation_id == operation_id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_foreign_key_integrity_maps_to_operation_persistence_error(
    db_session_factory,
) -> None:
    async with db_session_factory() as session:
        repo = OperationRepository(session)
        session.add(
            OperationEvent(
                id=new_uuid7(),
                operation_id=new_uuid7(),
                sequence=1,
                event_type=EVENT_TYPE_STATE_CHANGED,
                details={},
            )
        )
        with pytest.raises(
            OperationPersistenceError, match="operation persistence failed"
        ) as exc_info:
            await repo._flush_or_raise()
        formatted = "".join(traceback.format_exception_only(type(exc_info.value), exc_info.value))
        assert "IntegrityError" not in formatted
        assert "fk_operation_events" not in formatted


@pytest.mark.asyncio
async def test_duplicate_event_primary_key_maps_to_operation_persistence_error(
    db_tx: psycopg.Connection,
    db_session_factory,
) -> None:
    operation_id, _ = await _seed_accepted_operation(db_tx, db_session_factory)

    uow = SqlAlchemyUnitOfWork(db_session_factory)
    async with uow:
        service = OperationService(uow.operations)
        await service.transition_operation(
            operation_id=operation_id,
            expected_version=1,
            to_state=OperationState.QUEUED,
            details={"phase": "first"},
        )
        await uow.commit()

    async with db_session_factory() as session:
        existing_event_id = await session.scalar(
            select(OperationEvent.id)
            .where(OperationEvent.operation_id == operation_id)
            .order_by(OperationEvent.sequence)
            .limit(1)
        )
        assert existing_event_id is not None
        repo = OperationRepository(session)
        session.add(
            OperationEvent(
                id=existing_event_id,
                operation_id=operation_id,
                sequence=99,
                event_type=EVENT_TYPE_PROGRESS,
                details={},
            )
        )
        with pytest.raises(
            OperationPersistenceError, match="operation persistence failed"
        ) as exc_info:
            await repo._flush_or_raise()
        _assert_redacted_public_exception(exc_info.value)
