"""CPS-103 Task 1: SqlAlchemy unit-of-work lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def _session_factory(session: AsyncMock) -> async_sessionmaker[AsyncSession]:
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_normal_exit_without_commit_rolls_back_and_closes() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    async with uow:
        _ = uow.session

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_commit_commits_once_and_closes_without_rollback() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    async with uow:
        await uow.commit()

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_in_block_rolls_back_closes_and_propagates() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(RuntimeError, match="force rollback"):
        async with uow:
            raise RuntimeError("force rollback")

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_error_rolls_back_closes_and_propagates() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(asyncio.CancelledError):
        async with uow:
            raise asyncio.CancelledError()

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_closes_and_propagates_original_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.commit.side_effect = RuntimeError("commit failed")
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(RuntimeError, match="commit failed"):
        async with uow:
            await uow.commit()

    session.commit.assert_awaited_once()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_exit_rollback_failure_propagates_closes_and_allows_reuse() -> None:
    first_session = AsyncMock(spec=AsyncSession)
    first_session.rollback.side_effect = RuntimeError("rollback failed")
    second_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock(side_effect=[first_session, second_session])
    uow = SqlAlchemyUnitOfWork(factory)

    with pytest.raises(RuntimeError, match="rollback failed"):
        async with uow:
            pass

    first_session.close.assert_awaited_once()
    async with uow:
        assert uow.session is second_session


@pytest.mark.asyncio
async def test_committed_exit_close_failure_propagates_and_allows_reuse() -> None:
    first_session = AsyncMock(spec=AsyncSession)
    first_session.close.side_effect = RuntimeError("close failed")
    second_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock(side_effect=[first_session, second_session])
    uow = SqlAlchemyUnitOfWork(factory)

    with pytest.raises(RuntimeError, match="close failed"):
        async with uow:
            await uow.commit()

    first_session.rollback.assert_not_awaited()
    async with uow:
        assert uow.session is second_session


@pytest.mark.asyncio
async def test_normal_exit_rollback_and_close_failure_raises_rollback_with_close_note() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.rollback.side_effect = RuntimeError("rollback failed")
    session.close.side_effect = RuntimeError("close failed")
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(RuntimeError, match="rollback failed") as exc_info:
        async with uow:
            pass

    note_text = "".join(exc_info.value.__notes__)
    assert "RuntimeError" in note_text
    assert "close failed" not in note_text
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_failure_note_does_not_leak_sensitive_close_message() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.rollback.side_effect = RuntimeError("rollback failed")
    forbidden_token = "must-not-" + "leak"
    dsn_fragment = "postgresql+psycopg://cps:" + forbidden_token + "@127.0.0.1:5432/cps"
    session.close.side_effect = RuntimeError(dsn_fragment)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(RuntimeError, match="rollback failed") as exc_info:
        async with uow:
            pass

    serialized = str(exc_info.value) + "".join(exc_info.value.__notes__)
    assert forbidden_token not in serialized
    assert dsn_fragment not in serialized
    assert "RuntimeError" in serialized
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_failure_keeps_commit_error_when_rollback_raises_cancelled() -> None:
    first_session = AsyncMock(spec=AsyncSession)
    first_session.commit.side_effect = RuntimeError("commit failed")
    first_session.rollback.side_effect = asyncio.CancelledError()
    second_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock(side_effect=[first_session, second_session])
    uow = SqlAlchemyUnitOfWork(factory)

    with pytest.raises(RuntimeError, match="commit failed"):
        async with uow:
            await uow.commit()

    first_session.commit.assert_awaited_once()
    first_session.rollback.assert_awaited_once()
    first_session.close.assert_awaited_once()

    async with uow:
        assert uow.session is second_session


@pytest.mark.asyncio
async def test_business_error_with_rollback_and_close_failures_keeps_business_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.rollback.side_effect = RuntimeError("rollback failed")
    session.close.side_effect = RuntimeError("close failed")
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(ValueError, match="business failure"):
        async with uow:
            raise ValueError("business failure")

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollback_failure_during_exception_does_not_mask_business_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.rollback.side_effect = RuntimeError("rollback failed")
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    with pytest.raises(ValueError, match="business failure"):
        async with uow:
            raise ValueError("business failure")

    session.close.assert_awaited_once()
    for call in session.rollback.await_args_list:
        assert call is not None


@pytest.mark.asyncio
async def test_session_outside_context_raises_lifecycle_error() -> None:
    uow = SqlAlchemyUnitOfWork(_session_factory(AsyncMock(spec=AsyncSession)))

    with pytest.raises(RuntimeError, match="not active"):
        _ = uow.session


@pytest.mark.asyncio
async def test_commit_outside_context_raises_lifecycle_error() -> None:
    uow = SqlAlchemyUnitOfWork(_session_factory(AsyncMock(spec=AsyncSession)))

    with pytest.raises(RuntimeError, match="not active"):
        await uow.commit()


@pytest.mark.asyncio
async def test_double_commit_raises_lifecycle_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    async with uow:
        await uow.commit()
        with pytest.raises(RuntimeError, match="already committed"):
            await uow.commit()

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reenter_active_unit_of_work_raises_lifecycle_error() -> None:
    session = AsyncMock(spec=AsyncSession)
    uow = SqlAlchemyUnitOfWork(_session_factory(session))

    async with uow:
        with pytest.raises(RuntimeError, match="already active"):
            async with uow:
                pass


@pytest.mark.asyncio
async def test_sequential_reuse_after_close_creates_new_session() -> None:
    first_session = AsyncMock(spec=AsyncSession)
    second_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock(side_effect=[first_session, second_session])
    uow = SqlAlchemyUnitOfWork(factory)

    async with uow:
        assert uow.session is first_session

    async with uow:
        assert uow.session is second_session

    first_session.close.assert_awaited_once()
    second_session.close.assert_awaited_once()
