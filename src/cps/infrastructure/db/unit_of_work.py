"""Transactional unit-of-work for async SQLAlchemy sessions."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """Manage one async session lifecycle per context block."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False
        self._rollback_attempted = False

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            msg = "Unit of work already active"
            raise RuntimeError(msg)
        self._session = self._session_factory()
        self._committed = False
        self._rollback_attempted = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        session = self._session
        committed = self._committed
        rollback_attempted = self._rollback_attempted
        self._session = None
        self._committed = False
        self._rollback_attempted = False

        rollback_error: BaseException | None = None
        close_error: BaseException | None = None

        if session is not None and not committed and not rollback_attempted:
            try:
                await session.rollback()
            except BaseException as err:
                rollback_error = err

        if session is not None:
            try:
                await session.close()
            except BaseException as err:
                close_error = err

        if exc_type is not None:
            return False

        if committed:
            if close_error is not None:
                raise close_error
            return False

        if rollback_error is not None:
            if close_error is not None:
                rollback_error.add_note(
                    "Additional cleanup failure while closing session: "
                    + type(close_error).__name__
                )
            raise rollback_error

        if close_error is not None:
            raise close_error

        return False

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            msg = "Unit of work is not active"
            raise RuntimeError(msg)
        return self._session

    async def commit(self) -> None:
        if self._session is None:
            msg = "Unit of work is not active"
            raise RuntimeError(msg)
        if self._committed:
            msg = "Unit of work already committed"
            raise RuntimeError(msg)
        try:
            await self._session.commit()
        except Exception as commit_error:
            self._rollback_attempted = True
            try:
                await self._session.rollback()
            except BaseException:
                pass
            raise commit_error
        self._committed = True
