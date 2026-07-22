"""PostgreSQL transactional outbox persistence."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import CursorResult, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cps.domain.messaging.outbox import (
    ClaimedOutboxMessage,
    OutboxClaim,
    OutboxDraft,
    PublishResult,
)
from cps.identifiers import new_uuid7
from cps.infrastructure.db.models.enums import OutboxPublishState
from cps.infrastructure.db.models.outbox_messages import OutboxMessage

LEASE_DURATION = timedelta(seconds=60)
MAX_CLAIM_BATCH_SIZE = 100


class OutboxPersistenceError(RuntimeError):
    """Stable persistence failure for the outbox boundary."""


class OutboxRepository:
    """Repository whose caller owns commit and rollback boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, draft: OutboxDraft) -> OutboxMessage:
        row = OutboxMessage(
            id=new_uuid7(),
            aggregate_type=draft.aggregate_type,
            aggregate_id=draft.aggregate_id,
            message_id=draft.message_id,
            message_type=draft.message_type,
            routing_key=draft.routing_key,
            payload=copy.deepcopy(draft.payload),
            publish_state=OutboxPublishState.PENDING,
            attempt_count=0,
            next_attempt_at=draft.occurred_at,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def claim_due(
        self,
        *,
        claimed_by: str,
        batch_size: int,
        now: datetime,
        max_attempts: int,
    ) -> list[ClaimedOutboxMessage]:
        if not claimed_by:
            raise OutboxPersistenceError("claim owner is required")
        if batch_size < 1 or batch_size > MAX_CLAIM_BATCH_SIZE:
            raise OutboxPersistenceError("claim batch size is out of range")
        if max_attempts != 3:
            raise OutboxPersistenceError("maximum attempts must be canonical default")
        _require_utc(now)
        eligible = or_(
            and_(
                OutboxMessage.publish_state == OutboxPublishState.PENDING,
                OutboxMessage.next_attempt_at <= now,
            ),
            and_(
                OutboxMessage.publish_state == OutboxPublishState.CLAIMED,
                OutboxMessage.claim_expires_at <= now,
            ),
        )
        result = await self._session.execute(
            select(OutboxMessage)
            .where(eligible)
            .order_by(OutboxMessage.next_attempt_at, OutboxMessage.created_at, OutboxMessage.id)
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        )
        rows = list(result.scalars())
        claims: list[ClaimedOutboxMessage] = []
        for row in rows:
            next_attempt = row.attempt_count + 1
            if next_attempt > max_attempts:
                row.publish_state = OutboxPublishState.FAILED
                row.claimed_by = None
                row.claim_token = None
                row.claim_expires_at = None
                row.last_error = "MAX_ATTEMPTS_EXCEEDED"
                row.version += 1
                continue
            token = uuid.uuid4()
            expires_at = now + LEASE_DURATION
            row.publish_state = OutboxPublishState.CLAIMED
            row.attempt_count = next_attempt
            row.claimed_by = claimed_by
            row.claim_token = token
            row.claim_expires_at = expires_at
            row.version += 1
            claims.append(
                ClaimedOutboxMessage(
                    claim=OutboxClaim(row_id=row.id, claimed_by=claimed_by, claim_token=token),
                    message_id=row.message_id,
                    message_type=row.message_type,
                    routing_key=row.routing_key,
                    payload=copy.deepcopy(row.payload),
                    correlation_id=uuid.UUID(str(row.payload["correlation_id"])),
                    attempt_count=next_attempt,
                    max_attempts=max_attempts,
                    claim_expires_at=expires_at,
                    occurred_at=_require_utc(row.created_at),
                )
            )
        await self._session.flush()
        return claims

    async def mark_published(self, claim: OutboxClaim, *, now: datetime) -> PublishResult:
        _require_utc(now)
        result = await self._session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == claim.row_id,
                OutboxMessage.publish_state == OutboxPublishState.CLAIMED,
                OutboxMessage.claimed_by == claim.claimed_by,
                OutboxMessage.claim_token == claim.claim_token,
            )
            .values(
                publish_state=OutboxPublishState.PUBLISHED,
                published_at=now,
                claimed_by=None,
                claim_token=None,
                claim_expires_at=None,
                version=OutboxMessage.version + 1,
            )
        )
        finalized = isinstance(result, CursorResult) and result.rowcount == 1
        return PublishResult(finalized=finalized, stale=not finalized)

    async def release_failed_publish(
        self,
        claim: OutboxClaim,
        *,
        now: datetime,
        max_attempts: int,
        error_code: str,
    ) -> PublishResult:
        _require_utc(now)
        if error_code not in {
            "PUBLISH_TIMEOUT",
            "PUBLISH_AMQP_ERROR",
            "MISSING_CONFIRMATION",
            "NEGATIVE_CONFIRMATION",
        }:
            raise OutboxPersistenceError("invalid publish failure code")
        row = await self._locked_claim(claim)
        if row is None:
            return PublishResult(finalized=False, stale=True)
        if row.attempt_count >= max_attempts:
            row.publish_state = OutboxPublishState.FAILED
        else:
            row.publish_state = OutboxPublishState.PENDING
            row.next_attempt_at = now + timedelta(seconds=2 ** (row.attempt_count - 1))
        row.claimed_by = None
        row.claim_token = None
        row.claim_expires_at = None
        row.last_error = error_code
        row.version += 1
        await self._session.flush()
        return PublishResult(finalized=True)

    async def _locked_claim(self, claim: OutboxClaim) -> OutboxMessage | None:
        result = await self._session.execute(
            select(OutboxMessage)
            .where(
                OutboxMessage.id == claim.row_id,
                OutboxMessage.publish_state == OutboxPublishState.CLAIMED,
                OutboxMessage.claimed_by == claim.claimed_by,
                OutboxMessage.claim_token == claim.claim_token,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise OutboxPersistenceError("timestamp must be timezone-aware UTC")
    return value
