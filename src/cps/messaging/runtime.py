"""CPS worker runtime: RabbitMQ connection, topology, and inbox consumer."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import cast

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cps.config import Settings
from cps.infrastructure.db.engine import create_database_engine
from cps.infrastructure.db.session import create_session_factory
from cps.infrastructure.messaging.constants import (
    DEFAULT_PREFETCH_COUNT,
    DEFAULT_RECONNECT_BASE_DELAY_SECONDS,
    DEFAULT_RECONNECT_MAX_DELAY_SECONDS,
    QUEUE_CPS_EVENT,
)
from cps.infrastructure.messaging.inbox_consumer import EventInboxConsumer
from cps.infrastructure.messaging.outbox_publisher import OutboxPublisher
from cps.infrastructure.messaging.publisher import ConfirmedPublisher
from cps.infrastructure.messaging.topology import (
    DeclaredEventTopology,
    EventTopologyBuilder,
    TopologyChannel,
)
from cps.messaging.lifecycle import WorkerLifecycle

logger = logging.getLogger(__name__)

__all__ = ["WorkerLifecycle", "run_worker"]

ConnectFn = Callable[..., Awaitable[AbstractRobustConnection]]


class SessionEndReason(str, Enum):
    STOP = "stop"
    SESSION_LOST = "session_lost"


@dataclass
class _WorkerResources:
    lifecycle: WorkerLifecycle
    settings: Settings
    connect_fn: ConnectFn
    once: bool
    stop_event: asyncio.Event | None = None
    retry_ttls_ms: tuple[int, int] | None = None
    db_engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    connection: AbstractRobustConnection | None = None
    channel: AbstractChannel | None = None
    topology: DeclaredEventTopology | None = None
    consumer: EventInboxConsumer | None = None
    consumer_tag: str | None = None
    session_watcher: asyncio.Task[None] | None = field(default=None, repr=False)
    primary_error: BaseException | None = field(default=None, repr=False)

    async def connect(self) -> None:
        self.connection = await self.connect_fn(
            self.settings.require_rabbitmq_url,
            timeout=5,
            heartbeat=30,
        )
        logger.info("cps worker connected to rabbitmq")

    async def open_channel(self) -> None:
        if self.connection is None:
            msg = "worker connection is not established"
            raise RuntimeError(msg)
        self.channel = await self.connection.channel(publisher_confirms=True)
        await self.channel.set_qos(prefetch_count=DEFAULT_PREFETCH_COUNT)

    async def declare_topology(self) -> None:
        if self.channel is None:
            msg = "worker channel is not established"
            raise RuntimeError(msg)
        self.topology = await EventTopologyBuilder().declare(
            cast(TopologyChannel, self.channel),
            retry_ttls_ms=self.retry_ttls_ms,
        )

    def create_consumer(self) -> EventInboxConsumer:
        if self.topology is None or self.session_factory is None:
            msg = "worker topology or database session factory is not ready"
            raise RuntimeError(msg)
        self.consumer = EventInboxConsumer(
            lifecycle=self.lifecycle,
            publisher=ConfirmedPublisher(),
            retry_exchange=self.topology.retry_exchange,
            session_factory=self.session_factory,
            consumer_name=QUEUE_CPS_EVENT,
            channel=self.channel,
        )
        return self.consumer

    async def start_consumer(self) -> None:
        if self.consumer is None or self.channel is None or self.topology is None:
            msg = "worker consumer is not initialized"
            raise RuntimeError(msg)
        self.consumer_tag = await self.consumer.start(self.channel, self.topology.event_queue)

    async def teardown_session(self) -> None:
        await self._cancel_session_watcher()
        if self.consumer is not None:
            try:
                await self.consumer.stop_session()
            except Exception as exc:
                self._remember_error(exc)
        self.consumer = None
        self.consumer_tag = None
        if self.channel is not None and not self.channel.is_closed:
            try:
                await self.channel.close()
            except Exception as exc:
                self._remember_error(exc)
        self.channel = None
        if self.connection is not None and not self.connection.is_closed:
            try:
                await self.connection.close()
            except Exception as exc:
                self._remember_error(exc)
        self.connection = None
        self.topology = None

    async def shutdown(self) -> None:
        self.lifecycle.begin_shutdown()
        await self.teardown_session()
        if self.db_engine is not None:
            await self.db_engine.dispose()
            self.db_engine = None

    async def _cancel_session_watcher(self) -> None:
        if self.session_watcher is None:
            return
        self.session_watcher.cancel()
        try:
            await self.session_watcher
        except asyncio.CancelledError:
            pass
        self.session_watcher = None

    def _remember_error(self, exc: BaseException) -> None:
        if self.primary_error is None:
            self.primary_error = exc


async def run_worker(
    *,
    settings: Settings,
    lifecycle: WorkerLifecycle | None = None,
    once: bool = False,
    stop_event: asyncio.Event | None = None,
    connect: ConnectFn | None = None,
    retry_ttls_ms: tuple[int, int] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    publish_outbox: bool = False,
) -> None:
    """Run the CPS inbox consumer and, in production, the outbox dispatcher."""
    resources = _WorkerResources(
        lifecycle=lifecycle or WorkerLifecycle(),
        settings=settings,
        connect_fn=connect or aio_pika.connect_robust,
        once=once,
        stop_event=stop_event,
        retry_ttls_ms=retry_ttls_ms,
    )
    if session_factory is not None:
        resources.session_factory = session_factory
        resources.db_engine = None
    else:
        resources.db_engine = create_database_engine(settings.require_database_url)
        resources.session_factory = create_session_factory(resources.db_engine)
    outbox_task: asyncio.Task[None] | None = None
    if publish_outbox and not once:
        if resources.session_factory is None:
            msg = "outbox publisher requires a session factory"
            raise RuntimeError(msg)
        outbox_publisher = OutboxPublisher(
            session_factory=resources.session_factory,
            rabbitmq_url=settings.require_rabbitmq_url,
            publisher_id=settings.service_name,
        )
        outbox_task = asyncio.create_task(_run_outbox_publisher(outbox_publisher))
    reconnect_attempt = 0

    try:
        while resources.lifecycle.accepting_work or once:
            if _stop_requested(resources):
                break
            try:
                await resources.connect()
                await resources.open_channel()
                await resources.declare_topology()
                resources.create_consumer()
                if once:
                    logger.info("cps worker ready")
                    break

                await resources.start_consumer()
                logger.info("cps worker ready")
                reconnect_attempt = 0
                reason = await _wait_for_session_end(resources)
                if reason is SessionEndReason.STOP:
                    break
                logger.warning("cps worker session lost; reconnecting")
                await resources.teardown_session()
                reconnect_attempt += 1
                await _reconnect_delay(reconnect_attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if once:
                    raise
                if _stop_requested(resources):
                    break
                if not resources.lifecycle.accepting_work:
                    raise
                logger.warning(
                    "cps worker session failed; reconnecting",
                    extra={"error_type": type(exc).__name__},
                )
                await resources.teardown_session()
                reconnect_attempt += 1
                await _reconnect_delay(reconnect_attempt)
    finally:
        if outbox_task is not None:
            outbox_task.cancel()
            try:
                await outbox_task
            except asyncio.CancelledError:
                pass
        await resources.shutdown()
        logger.info("cps worker disconnected from rabbitmq")


async def _run_outbox_publisher(publisher: OutboxPublisher) -> None:
    """Continuously dispatch committed commands from the transactional outbox."""
    while True:
        try:
            published = await publisher.publish_due(batch_size=100)
            await asyncio.sleep(0.1 if published else 0.5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "cps outbox publish failed; retrying",
                extra={"error_type": type(exc).__name__},
            )
            await asyncio.sleep(1.0)


async def _wait_for_session_end(resources: _WorkerResources) -> SessionEndReason:
    session_lost = asyncio.Event()
    resources.session_watcher = asyncio.create_task(_watch_session_closure(resources, session_lost))
    stop_event = _worker_stop_event(resources)
    stop_task = asyncio.create_task(stop_event.wait())
    lost_task = asyncio.create_task(session_lost.wait())
    try:
        done, pending = await asyncio.wait(
            {stop_task, lost_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if lost_task in done and not stop_event.is_set():
            return SessionEndReason.SESSION_LOST
        return SessionEndReason.STOP
    finally:
        await resources._cancel_session_watcher()


def _worker_stop_event(resources: _WorkerResources) -> asyncio.Event:
    if resources.stop_event is not None:
        return resources.stop_event
    event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop(*_args: object) -> None:
        resources.lifecycle.begin_shutdown()
        event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            pass
    resources.stop_event = event
    return event


async def _watch_session_closure(
    resources: _WorkerResources,
    session_lost: asyncio.Event,
) -> None:
    while resources.lifecycle.accepting_work:
        connection = resources.connection
        channel = resources.channel
        if connection is None or getattr(connection, "is_closed", False):
            session_lost.set()
            return
        if channel is None or getattr(channel, "is_closed", False):
            session_lost.set()
            return
        await asyncio.sleep(0.05)


async def _reconnect_delay(attempt: int) -> None:
    delay = min(
        DEFAULT_RECONNECT_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
        DEFAULT_RECONNECT_MAX_DELAY_SECONDS,
    )
    await asyncio.sleep(delay)


def _stop_requested(resources: _WorkerResources) -> bool:
    if resources.stop_event is not None and resources.stop_event.is_set():
        resources.lifecycle.begin_shutdown()
        return True
    return False
