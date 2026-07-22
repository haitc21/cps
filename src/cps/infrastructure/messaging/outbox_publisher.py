"""Transactional outbox publisher with RabbitMQ publisher confirms."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import aio_pika
from pamqp.commands import Basic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cps.contracts.messages.envelope import MessageEnvelope
from cps.domain.messaging.outbox import ClaimedOutboxMessage
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

COMMAND_EXCHANGE = "cmp.cloud.command.v1"
PUBLISH_CONFIRM_TIMEOUT_SECONDS = 10.0

ConnectFn = Callable[..., Awaitable[Any]]


class PublishConfirmError(RuntimeError):
    """Stable failure code for broker publication/confirmation failures."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OutboxPublisher:
    """Claim, commit, publish, then finalize in a separate transaction."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        rabbitmq_url: str,
        publisher_id: str,
        max_attempts: int = 3,
        connect: ConnectFn | None = None,
    ) -> None:
        if not publisher_id:
            raise ValueError("publisher id is required")
        if not rabbitmq_url:
            raise ValueError("rabbitmq url is required")
        if max_attempts != 3:
            raise ValueError("maximum attempts must equal canonical default")
        self._session_factory = session_factory
        self._rabbitmq_url = rabbitmq_url
        self._publisher_id = publisher_id
        self._max_attempts = max_attempts
        self._connect = connect or aio_pika.connect_robust

    async def publish_due(self, *, batch_size: int, now: datetime | None = None) -> int:
        claim_now = now or datetime.now(UTC)
        uow = SqlAlchemyUnitOfWork(self._session_factory)
        async with uow:
            claimed = await uow.outbox.claim_due(
                claimed_by=self._publisher_id,
                batch_size=batch_size,
                now=claim_now,
                max_attempts=self._max_attempts,
            )
            await uow.commit()

        # The claim UoW is closed before any connection, publish, or confirm await.
        if not claimed:
            return 0
        connection: Any | None = None
        channel: Any | None = None
        primary_error: BaseException | None = None
        try:
            connection, channel, exchange = await self._open_exchange()
        except asyncio.CancelledError:
            raise
        except PublishConfirmError as error:
            for message in claimed:
                await self._record_failure(message, error.code)
            return 0
        try:
            finalized = 0
            for message in claimed:
                try:
                    await self._publish_confirmed(exchange, message)
                except asyncio.CancelledError:
                    raise
                except PublishConfirmError as error:
                    await self._record_failure(message, error.code)
                else:
                    finalized += await self._record_success(message)
            return finalized
        except BaseException as error:
            primary_error = error
            raise
        finally:
            await _close_resources(channel, connection, primary_error)

    async def _open_exchange(self) -> tuple[Any, Any, Any]:
        connection: Any | None = None
        channel: Any | None = None
        try:
            connection = await self._connect(
                self._rabbitmq_url,
                timeout=PUBLISH_CONFIRM_TIMEOUT_SECONDS,
            )
            channel = await connection.channel(publisher_confirms=True)
            exchange = await channel.declare_exchange(
                COMMAND_EXCHANGE,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            return connection, channel, exchange
        except asyncio.CancelledError:
            await _close_resources(channel, connection, asyncio.CancelledError())
            raise
        except TimeoutError:
            await _close_resources(channel, connection, RuntimeError())
            raise PublishConfirmError("PUBLISH_TIMEOUT") from None
        except (aio_pika.exceptions.AMQPException, ConnectionError, OSError):
            await _close_resources(channel, connection, RuntimeError())
            raise PublishConfirmError("PUBLISH_AMQP_ERROR") from None
        except BaseException as error:
            await _close_resources(channel, connection, error)
            raise

    async def _publish_confirmed(self, exchange: Any, message: ClaimedOutboxMessage) -> None:
        try:
            envelope = MessageEnvelope.model_validate(message.payload)
            body = json.dumps(
                envelope.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
            ).encode()
            broker_message = aio_pika.Message(
                body=body,
                headers=message.delivery_metadata.model_dump(
                    by_alias=True,
                    mode="json",
                    exclude_none=True,
                ),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=str(message.message_id),
                correlation_id=str(message.correlation_id),
                content_type="application/json",
            )
            confirmation = await exchange.publish(
                broker_message,
                routing_key=message.routing_key,
                mandatory=True,
                timeout=PUBLISH_CONFIRM_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise PublishConfirmError("PUBLISH_TIMEOUT") from None
        except (aio_pika.exceptions.AMQPException, ConnectionError, OSError):
            raise PublishConfirmError("PUBLISH_AMQP_ERROR") from None
        except ValueError:
            raise PublishConfirmError("PUBLISH_AMQP_ERROR") from None
        if confirmation is None:
            raise PublishConfirmError("MISSING_CONFIRMATION")
        if not isinstance(confirmation, Basic.Ack):
            raise PublishConfirmError("NEGATIVE_CONFIRMATION")

    async def _record_success(self, message: ClaimedOutboxMessage) -> int:
        uow = SqlAlchemyUnitOfWork(self._session_factory)
        async with uow:
            result = await uow.outbox.mark_published(message.claim, now=datetime.now(UTC))
            await uow.commit()
        return int(result.finalized)

    async def _record_failure(self, message: ClaimedOutboxMessage, code: str) -> None:
        uow = SqlAlchemyUnitOfWork(self._session_factory)
        async with uow:
            await uow.outbox.release_failed_publish(
                message.claim,
                now=datetime.now(UTC),
                max_attempts=self._max_attempts,
                error_code=code,
            )
            await uow.commit()


async def _close_resources(
    channel: Any | None,
    connection: Any | None,
    primary_error: BaseException | None,
) -> None:
    """Close resources without allowing cleanup to mask a primary failure."""

    async def close_all() -> BaseException | None:
        first_failure: BaseException | None = None
        for resource in (channel, connection):
            if resource is None:
                continue
            try:
                await resource.close()
            except BaseException as error:
                if first_failure is None:
                    first_failure = error
        return first_failure

    task = asyncio.create_task(close_all())
    cleanup_cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cleanup_cancelled = True
    cleanup_failure = task.result()
    if primary_error is not None:
        return
    if cleanup_cancelled:
        raise asyncio.CancelledError()
    if isinstance(cleanup_failure, KeyboardInterrupt | SystemExit):
        raise cleanup_failure
    if cleanup_failure is not None:
        raise PublishConfirmError("PUBLISH_CLEANUP_ERROR")
