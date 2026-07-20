"""CPS worker runtime: RabbitMQ connection and lifecycle loop."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika

from cps.config import Settings
from cps.messaging.lifecycle import WorkerLifecycle

logger = logging.getLogger(__name__)

__all__ = ["WorkerLifecycle", "run_worker"]

ConnectFn = Callable[..., Awaitable[Any]]


async def run_worker(
    *,
    settings: Settings,
    lifecycle: WorkerLifecycle | None = None,
    once: bool = False,
    stop_event: asyncio.Event | None = None,
    connect: ConnectFn | None = None,
) -> None:
    """Connect to RabbitMQ and keep the CPS worker alive until shutdown.

    Sprint 0 provides a minimal durable process lifecycle; outbox/inbox
    consumers arrive in later sprints.
    """
    worker_lifecycle = lifecycle or WorkerLifecycle()
    connect_fn: ConnectFn = connect or aio_pika.connect_robust
    connection = await connect_fn(settings.require_rabbitmq_url, timeout=5)
    logger.info("cps worker connected to rabbitmq")

    try:
        if once:
            worker_lifecycle.begin_shutdown()
            return

        event = stop_event or asyncio.Event()
        if stop_event is None:
            loop = asyncio.get_running_loop()

            def _request_stop(*_args: object) -> None:
                worker_lifecycle.begin_shutdown()
                event.set()

            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, _request_stop)
                except (NotImplementedError, RuntimeError):
                    pass

        await event.wait()
    finally:
        worker_lifecycle.begin_shutdown()
        await connection.close()
        logger.info("cps worker disconnected from rabbitmq")
