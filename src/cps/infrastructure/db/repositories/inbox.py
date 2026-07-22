"""PostgreSQL inbox deduplication persistence."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from sqlalchemy import CursorResult, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cps.domain.messaging.inbox import (
    InboxInsertResult,
    InboxInsertStatus,
    InboxReceiveDraft,
    InboxValidationError,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import InboxProcessState
from cps.infrastructure.db.models.inbox_messages import InboxMessage


class InboxPersistenceError(RuntimeError):
    """Stable persistence failure for the inbox boundary."""


class InboxRepository:
    """Repository whose caller owns commit and rollback boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_insert_received(self, draft: InboxReceiveDraft) -> InboxInsertResult:
        if not draft.consumer_name:
            raise InboxPersistenceError("consumer name is required")
        row_id = new_uuid7()
        stmt = (
            pg_insert(InboxMessage)
            .values(
                id=row_id,
                consumer_name=draft.consumer_name,
                message_id=draft.message_id,
                message_type=draft.message_type,
                payload=copy.deepcopy(draft.payload),
                process_state=InboxProcessState.RECEIVED,
                received_at=draft.received_at,
            )
            .on_conflict_do_nothing(
                index_elements=["consumer_name", "message_id"],
            )
            .returning(InboxMessage.id)
        )
        result = await self._session.execute(stmt)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            return InboxInsertResult(
                status=InboxInsertStatus.INSERTED,
                inbox_id=inserted_id,
            )

        for _attempt in range(2):
            existing = await self.get_by_consumer_message(
                consumer_name=draft.consumer_name,
                message_id=draft.message_id,
            )
            if existing is None:
                retry_result = await self._session.execute(stmt)
                retry_id = retry_result.scalar_one_or_none()
                if retry_id is not None:
                    return InboxInsertResult(
                        status=InboxInsertStatus.INSERTED,
                        inbox_id=retry_id,
                    )
                continue
            if existing.process_state is InboxProcessState.PROCESSED:
                return InboxInsertResult(status=InboxInsertStatus.ALREADY_PROCESSED)
            msg = "conflicting inbox row is not processed"
            raise InboxPersistenceError(msg)
        msg = "inbox insert conflict could not be resolved"
        raise InboxPersistenceError(msg)

    async def get_by_consumer_message(
        self,
        *,
        consumer_name: str,
        message_id: uuid.UUID,
    ) -> InboxMessage | None:
        result = await self._session.execute(
            select(InboxMessage).where(
                InboxMessage.consumer_name == consumer_name,
                InboxMessage.message_id == message_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_processed(self, inbox_id: uuid.UUID, *, now: datetime) -> bool:
        _require_utc(now)
        result = await self._session.execute(
            update(InboxMessage)
            .where(
                InboxMessage.id == inbox_id,
                InboxMessage.process_state == InboxProcessState.RECEIVED,
            )
            .values(
                process_state=InboxProcessState.PROCESSED,
                processed_at=now,
            )
        )
        return isinstance(result, CursorResult) and result.rowcount == 1


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise InboxValidationError("timestamp must be timezone-aware UTC")
    return value
