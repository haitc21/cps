"""CPS event inbox consumer with deduplication and transactional processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage, AbstractQueue
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cps.contracts.messages.delivery import DeliveryMetadata
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.types import (
    INVENTORY_BATCH,
    INVENTORY_COMPLETED,
    OPERATION_COMPLETED,
    OPERATION_FAILED,
    OPERATION_PROGRESS,
)
from cps.domain.inventory.inbox_handler import InventoryEventError, InventoryInboxHandler
from cps.domain.messaging.inbox import InboxProcessOutcome, InboxReceiveDraft
from cps.domain.operations.errors import (
    ConcurrentUpdateError,
    EventOwnershipMismatchError,
    InvalidOperationTransitionError,
    InvalidProgressStateError,
    OperationNotFoundError,
    OperationPersistenceError,
)
from cps.domain.operations.inbox_handler import OperationInboxHandler, UnsupportedEventTypeError
from cps.infrastructure.db.repositories.inventory import InventorySyncIncompleteError
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from cps.infrastructure.messaging.constants import (
    DEFAULT_PREFETCH_COUNT,
    DEFAULT_SHUTDOWN_GRACE_SECONDS,
    EVENT_ROUTING_KEYS,
    QUEUE_CPS_EVENT,
)
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle
from cps.infrastructure.messaging.publisher import ConfirmedPublisher, PublishConfirmError
from cps.infrastructure.messaging.retry import (
    merge_envelope_delivery_headers,
    parse_event_delivery_metadata,
    publish_event_retry,
    resolve_event_routing_key,
)

logger = logging.getLogger(__name__)


SUPPORTED_EVENT_TYPES = frozenset(
    {
        INVENTORY_BATCH,
        INVENTORY_COMPLETED,
        OPERATION_PROGRESS,
        OPERATION_COMPLETED,
        OPERATION_FAILED,
    }
)


ConnectFn = Callable[..., Awaitable[Any]]


@dataclass
class DeliveryProcessingRecord:
    acked: bool = False

    rejected: bool = False

    reject_requeue: bool | None = None

    retry_published: bool = False

    committed: bool = False

    channel_closed: bool = False

    handler_called: bool = False

    @property
    def terminal_action_count(self) -> int:
        return sum(1 for value in (self.acked, self.rejected, self.channel_closed) if value)


class IncomingMessageProtocol(Protocol):
    body: bytes

    headers: Mapping[str, Any] | None

    routing_key: str | None

    async def ack(self, multiple: bool = False) -> None: ...

    async def reject(self, requeue: bool = False) -> None: ...


@dataclass
class EventInboxConsumer:
    lifecycle: WorkerLifecycle

    publisher: ConfirmedPublisher

    retry_exchange: AbstractExchange

    session_factory: async_sessionmaker[AsyncSession]

    consumer_name: str = QUEUE_CPS_EVENT

    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS

    channel: AbstractChannel | None = None

    _consumer_tag: str | None = field(default=None, init=False)

    _queue: AbstractQueue | None = field(default=None, init=False)

    async def start(self, channel: AbstractChannel, queue: AbstractQueue) -> str:
        self.channel = channel

        self._queue = queue

        await channel.set_qos(prefetch_count=DEFAULT_PREFETCH_COUNT)

        self._consumer_tag = await queue.consume(self._on_message, no_ack=False)

        return self._consumer_tag

    async def stop_session(self) -> None:
        """Tear down this RabbitMQ consumer session without final worker shutdown."""
        if self._queue is not None and self._consumer_tag is not None:
            if self.channel is None or not self.channel.is_closed:
                await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None
            await self.lifecycle.wait_drained(self.shutdown_grace_seconds)
        if self.channel is not None and not self.channel.is_closed:
            await self.channel.close()
            self.channel = None

    async def stop(self) -> None:
        """Final worker shutdown: stop intake permanently and drain this session."""
        self.lifecycle.begin_shutdown()
        await self.stop_session()

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        if not self.lifecycle.accepting_work:
            return

        record = DeliveryProcessingRecord()

        try:
            await self.process_delivery(
                cast(IncomingMessageProtocol, message),
                record,
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.warning(
                "unexpected inbox consumer failure",
                extra={"error_type": type(exc).__name__},
            )

            if self.channel is not None and not getattr(self.channel, "is_closed", False):
                await self.channel.close()

    async def process_delivery(
        self,
        message: IncomingMessageProtocol,
        record: DeliveryProcessingRecord | None = None,
    ) -> tuple[str, bool]:
        actions = record or DeliveryProcessingRecord()

        try:
            raw = json.loads(message.body)

        except json.JSONDecodeError:
            logger.info(
                "rejecting malformed event payload",
                extra={"payload_sha256": hashlib.sha256(message.body).hexdigest()},
            )

            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        if not isinstance(raw, dict):
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        try:
            envelope = MessageEnvelope.model_validate(raw)

        except ValidationError:
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        if envelope.message_type not in SUPPORTED_EVENT_TYPES:
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        if envelope.message_type not in EVENT_ROUTING_KEYS:
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        try:
            metadata = parse_event_delivery_metadata(
                merge_envelope_delivery_headers(message.headers, envelope)
            )

            original_routing_key = resolve_event_routing_key(
                envelope,
                metadata,
                message.routing_key or "",
            )

        except (ValidationError, ValueError, TypeError):
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return "poison", False

        message_id = str(metadata.message_id)

        self.lifecycle.mark_in_flight(message_id)

        completed = False

        try:
            try:
                outcome = await self._process_inbox(envelope, actions)

            except asyncio.CancelledError:
                raise

            except (
                OperationNotFoundError,
                EventOwnershipMismatchError,
                InvalidProgressStateError,
                UnsupportedEventTypeError,
                InventoryEventError,
            ):
                await message.reject(requeue=False)

                actions.rejected = True

                actions.reject_requeue = False

                return message_id, False

            except (
                ConcurrentUpdateError,
                OperationPersistenceError,
                InvalidOperationTransitionError,
                InventorySyncIncompleteError,
            ):
                completed = await self._retry_or_reject(
                    message,
                    actions,
                    body=message.body,
                    metadata=metadata,
                    original_routing_key=original_routing_key,
                )

                return message_id, completed

            except Exception:
                completed = await self._retry_or_reject(
                    message,
                    actions,
                    body=message.body,
                    metadata=metadata,
                    original_routing_key=original_routing_key,
                )

                return message_id, completed

            if outcome.duplicate:
                actions.handler_called = False

            else:
                actions.handler_called = True

            completed = await self._ack_after_processing(message, actions, outcome)

            return message_id, completed

        finally:
            self.lifecycle.finish_or_nack(message_id, completed=completed)

    async def _ack_after_processing(
        self,
        message: IncomingMessageProtocol,
        actions: DeliveryProcessingRecord,
        outcome: InboxProcessOutcome,
    ) -> bool:
        if outcome.committed:
            actions.committed = True

        try:
            await message.ack()

            actions.acked = True

            return True

        except Exception:
            await self._close_channel_on_ack_failure(actions)

            return False

    async def _close_channel_on_ack_failure(self, actions: DeliveryProcessingRecord) -> None:
        if self.channel is not None and not getattr(self.channel, "is_closed", False):
            await self.channel.close()

            actions.channel_closed = True

    async def _process_inbox(
        self,
        envelope: MessageEnvelope,
        actions: DeliveryProcessingRecord,
    ) -> InboxProcessOutcome:
        """Insert inbox row, run handler, mark processed, and commit in one UoW."""

        now = datetime.now(UTC)

        draft = InboxReceiveDraft(
            consumer_name=self.consumer_name,
            message_id=envelope.message_id,
            message_type=envelope.message_type,
            payload=envelope.model_dump(mode="json"),
            received_at=now,
        )

        uow = SqlAlchemyUnitOfWork(self.session_factory)

        async with uow:
            insert_result = await uow.inbox.try_insert_received(draft)

            if insert_result.is_duplicate:
                return InboxProcessOutcome(duplicate=True, committed=False)

            if not insert_result.requires_processing or insert_result.inbox_id is None:
                msg = "inbox insert did not yield a row"

                raise OperationPersistenceError(msg)

            inbox_id = insert_result.inbox_id

            handler = OperationInboxHandler(uow.operations)
            if envelope.message_type in {INVENTORY_BATCH, INVENTORY_COMPLETED}:
                await InventoryInboxHandler(uow.inventory, uow.operations).handle(envelope)
            else:
                await handler.handle(envelope)
                result = envelope.payload.get("result", {})
                if envelope.message_type == OPERATION_COMPLETED and isinstance(result, dict):
                    instance = result.get("instance")
                    if isinstance(instance, dict):
                        await uow.inventory.persist_instance_result(
                            provider_connection_id=envelope.provider_connection_id,
                            sync_id=None,
                            instance=instance,
                        )

            marked = await uow.inbox.mark_processed(inbox_id, now=now)

            if not marked:
                msg = "inbox row could not be marked processed"

                raise OperationPersistenceError(msg)

            await uow.commit()

            actions.committed = True

        return InboxProcessOutcome(duplicate=False, committed=True)

    async def _retry_or_reject(
        self,
        message: IncomingMessageProtocol,
        actions: DeliveryProcessingRecord,
        *,
        body: bytes,
        metadata: DeliveryMetadata,
        original_routing_key: str,
    ) -> bool:
        if metadata.attempt >= metadata.max_attempts:
            await message.reject(requeue=False)

            actions.rejected = True

            actions.reject_requeue = False

            return False

        try:
            await publish_event_retry(
                self.publisher,
                self.retry_exchange,
                body=body,
                metadata=metadata,
                retry_reason="INBOX_HANDLER_ERROR",
                original_routing_key=original_routing_key,
            )

            actions.retry_published = True

        except PublishConfirmError:
            await self._close_channel_on_ack_failure(actions)

            return False

        try:
            await message.ack()

            actions.acked = True

            return True

        except Exception:
            await self._close_channel_on_ack_failure(actions)

            return False


async def reject_poison_delivery(message: IncomingMessageProtocol) -> None:
    await message.reject(requeue=False)
