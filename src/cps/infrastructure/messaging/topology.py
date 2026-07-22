"""RabbitMQ topology declaration for CPS-owned event resources."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from aio_pika.abc import AbstractExchange, AbstractQueue

from cps.infrastructure.messaging.constants import (
    ARG_DEAD_LETTER_EXCHANGE,
    ARG_DEAD_LETTER_ROUTING_KEY,
    ARG_MESSAGE_TTL,
    CPS_EVENT_RETRY_QUEUES,
    EVENT_QUEUE_ARGUMENTS,
    EVENT_QUEUE_BINDINGS,
    EXCHANGE_DLX,
    EXCHANGE_EVENT,
    EXCHANGE_RETRY,
    EXCHANGE_TYPE_DIRECT,
    EXCHANGE_TYPE_TOPIC,
    QUEUE_CPS_EVENT,
    QUEUE_CPS_EVENT_DLQ,
    ROUTING_KEY_CLOUD_OPERATION_RETRY,
    ROUTING_KEY_CPS_EVENT_DLQ,
)

logger = logging.getLogger(__name__)


class TopologyChannel(Protocol):
    async def declare_exchange(
        self,
        name: str,
        type: Any = ...,
        *,
        durable: bool = ...,
        auto_delete: bool = ...,
        passive: bool = ...,
        arguments: dict[str, Any] | None = ...,
        **kwargs: Any,
    ) -> AbstractExchange: ...

    async def declare_queue(
        self,
        name: str | None = ...,
        *,
        durable: bool = ...,
        exclusive: bool = ...,
        passive: bool = ...,
        auto_delete: bool = ...,
        arguments: dict[str, Any] | None = ...,
        **kwargs: Any,
    ) -> AbstractQueue: ...


@dataclass(frozen=True, slots=True)
class DeclaredEventTopology:
    event_exchange: AbstractExchange
    retry_exchange: AbstractExchange
    dlx_exchange: AbstractExchange
    event_queue: AbstractQueue
    retry_queues: tuple[AbstractQueue, ...]
    dlq_queue: AbstractQueue


class EventTopologyBuilder:
    """Declare CPS-owned RabbitMQ exchanges, queues, and bindings."""

    async def declare(
        self,
        channel: TopologyChannel,
        *,
        retry_ttls_ms: tuple[int, int] | None = None,
    ) -> DeclaredEventTopology:
        event_exchange = await channel.declare_exchange(
            EXCHANGE_EVENT,
            EXCHANGE_TYPE_TOPIC,
            durable=True,
            auto_delete=False,
        )
        retry_exchange = await channel.declare_exchange(
            EXCHANGE_RETRY,
            EXCHANGE_TYPE_DIRECT,
            durable=True,
            auto_delete=False,
        )
        dlx_exchange = await channel.declare_exchange(
            EXCHANGE_DLX,
            EXCHANGE_TYPE_TOPIC,
            durable=True,
            auto_delete=False,
        )

        event_queue = await channel.declare_queue(
            QUEUE_CPS_EVENT,
            durable=True,
            auto_delete=False,
            exclusive=False,
            arguments=EVENT_QUEUE_ARGUMENTS,
        )
        retry_queues: list[AbstractQueue] = []
        for index, retry_spec in enumerate(CPS_EVENT_RETRY_QUEUES):
            ttl_ms = retry_ttls_ms[index] if retry_ttls_ms is not None else retry_spec.ttl_ms
            retry_queue = await channel.declare_queue(
                retry_spec.queue_name,
                durable=True,
                auto_delete=False,
                exclusive=False,
                arguments={
                    ARG_MESSAGE_TTL: ttl_ms,
                    ARG_DEAD_LETTER_EXCHANGE: EXCHANGE_EVENT,
                    ARG_DEAD_LETTER_ROUTING_KEY: ROUTING_KEY_CLOUD_OPERATION_RETRY,
                },
            )
            retry_queues.append(retry_queue)

        dlq_queue = await channel.declare_queue(
            QUEUE_CPS_EVENT_DLQ,
            durable=True,
            auto_delete=False,
            exclusive=False,
        )

        for routing_key in EVENT_QUEUE_BINDINGS:
            await event_queue.bind(event_exchange, routing_key=routing_key)

        for retry_spec, retry_queue in zip(
            CPS_EVENT_RETRY_QUEUES,
            retry_queues,
            strict=True,
        ):
            await retry_queue.bind(retry_exchange, routing_key=retry_spec.routing_key)

        await dlq_queue.bind(dlx_exchange, routing_key=ROUTING_KEY_CPS_EVENT_DLQ)

        logger.info(
            "cps event topology declared",
            extra={
                "event_queue": QUEUE_CPS_EVENT,
                "retry_queues": [spec.queue_name for spec in CPS_EVENT_RETRY_QUEUES],
                "dlq_queue": QUEUE_CPS_EVENT_DLQ,
            },
        )
        return DeclaredEventTopology(
            event_exchange=event_exchange,
            retry_exchange=retry_exchange,
            dlx_exchange=dlx_exchange,
            event_queue=event_queue,
            retry_queues=tuple(retry_queues),
            dlq_queue=dlq_queue,
        )
